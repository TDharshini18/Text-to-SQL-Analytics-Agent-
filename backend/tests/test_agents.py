"""Tests for schema linking, the self-correction loop and the safety check.

The LLM is replaced by fakes, so these run offline:  python -m pytest
"""

import json
import sqlite3

import pytest

from app import config
from app.agents import pipeline, schema_linking
from app.agents.schema_agent import get_schema
from app.agents.schema_linking import connect_tables, lexical_links, link_schema, value_links
from app.services.sql_validator import UnsafeSQLError, validate_sql


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "shop.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, name TEXT, city TEXT);
        CREATE TABLE products (product_id INTEGER PRIMARY KEY, name TEXT, category TEXT);
        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY,
            customer_id INTEGER REFERENCES customers(customer_id),
            product_id INTEGER REFERENCES products(product_id),
            amount REAL
        );
        CREATE TABLE suppliers (supplier_id INTEGER PRIMARY KEY, company TEXT);
        INSERT INTO customers VALUES (1, 'Asha Iyer', 'Kochi'), (2, 'Ravi Reddy', 'New Delhi');
        INSERT INTO products VALUES (1, 'Laptop', 'Electronics'), (2, 'Desk', 'Furniture');
        INSERT INTO orders VALUES (1, 1, 1, 900), (2, 2, 2, 150), (3, 1, 2, 160);
        INSERT INTO suppliers VALUES (1, 'Acme');
        """
    )
    conn.commit()
    monkeypatch.setattr(config, "DB_PATH", path)
    pipeline._value_cache.clear()
    yield conn
    conn.close()


def fake_link_llm(tables, columns=()):
    def fake(system_prompt, user_prompt, json_mode=False):
        return json.dumps({"tables": list(tables), "columns": list(columns)})
    return fake


# ---------- schema linking ----------

def test_lexical_links_match_plural_and_column_names(db):
    hits = lexical_links("Which cities have the most orders?", get_schema(db))
    assert "orders" in hits
    assert ("city", 'column "city" in question') in hits["customers"]
    assert "suppliers" not in hits


def test_value_links_find_stored_values_and_prefer_longest(db):
    schema = get_schema(db)
    index = schema_linking.build_value_index(db, schema)
    found = value_links("How much did customers in new delhi spend on electronics?", index)
    assert {"table": "customers", "column": "city", "value": "New Delhi", "match": "exact"} in found
    assert {"table": "products", "column": "category", "value": "Electronics", "match": "exact"} in found


def test_foreign_keys_add_the_bridge_table(db):
    assert connect_tables(get_schema(db), {"customers", "products"}) == {"orders": "joins customers to products"}


def test_link_schema_combines_steps_and_leaves_out_unrelated_tables(db, monkeypatch):
    monkeypatch.setattr(schema_linking, "ask_llm", fake_link_llm(["products"], ["products.category"]))
    schema = get_schema(db)
    result = link_schema("Revenue per category for Kochi", schema, schema_linking.build_value_index(db, schema))
    assert set(result.tables) == {"customers", "orders", "products"}  # orders added as the bridge
    assert "suppliers" not in result.tables
    assert result.values == [{"table": "customers", "column": "city", "value": "Kochi", "match": "exact"}]
    assert result.method == "lexical+value+llm"  # "category" matches products.category by name
    assert result.columns["products"] == ["category"]


def test_link_schema_ignores_names_the_llm_invents(db, monkeypatch):
    monkeypatch.setattr(schema_linking, "ask_llm", fake_link_llm(["orders", "invoices"], ["orders.nope"]))
    result = link_schema("total sales", get_schema(db), [])
    assert result.tables == ["orders"]
    assert result.columns == {}


def test_link_schema_falls_back_to_all_tables_when_nothing_matches(db, monkeypatch):
    monkeypatch.setattr(schema_linking, "ask_llm", fake_link_llm([]))
    result = link_schema("hello there", get_schema(db), [])
    assert result.method == "fallback"
    assert len(result.tables) == 4


# ---------- self-correction loop ----------

def run(db, monkeypatch, replies, link_tables=("orders",), review=None):
    """Run the pipeline with a fake SQL agent that returns `replies` in order."""
    calls = []

    def fake_generate(question, schema_text, history):
        calls.append({"schema": schema_text, "history": list(history)})
        return replies[len(calls) - 1]

    monkeypatch.setattr(schema_linking, "ask_llm", fake_link_llm(link_tables))
    monkeypatch.setattr(pipeline, "generate_sql", fake_generate)
    monkeypatch.setattr(pipeline, "explain", lambda *a: "explained")
    monkeypatch.setattr(pipeline, "review_result", lambda *a: review)
    return list(pipeline.run_pipeline(db, "total sales")), calls


def test_repairs_a_failing_query_using_the_database_error(db, monkeypatch):
    events, calls = run(db, monkeypatch, ["SELECT SUM(amout) FROM orders", "SELECT SUM(amount) AS total FROM orders"])
    result = events[-1]["response"]
    assert result["results"] == [[1210.0]]
    attempts = result["trace"]["attempts"]
    assert [a["ok"] for a in attempts] == [False, True]
    assert "no such column: amout" in attempts[0]["error"]
    # The repair call saw the failed SQL and the exact error.
    assert calls[1]["history"][0][0] == "SELECT SUM(amout) FROM orders"
    assert attempts[0]["error"] in calls[1]["history"][0][1]


def test_unsafe_sql_is_rejected_and_repaired(db, monkeypatch):
    events, calls = run(db, monkeypatch, ["DELETE FROM orders", "SELECT COUNT(*) FROM orders"])
    attempts = events[-1]["response"]["trace"]["attempts"]
    assert attempts[0]["error"].startswith("Safety check")
    assert attempts[1]["ok"]


def test_missing_table_widens_to_the_full_schema(db, monkeypatch):
    events, calls = run(
        db, monkeypatch, ["SELECT company FROM supplier", "SELECT company FROM suppliers"], link_tables=["orders"]
    )
    assert 'TABLE "suppliers"' not in calls[0]["schema"]
    assert 'TABLE "suppliers"' in calls[1]["schema"]
    assert any(e["type"] == "widened" for e in events)
    assert events[-1]["response"]["results"] == [["Acme"]]


def test_gives_up_after_max_attempts(db, monkeypatch):
    with pytest.raises(pipeline.PipelineError) as err:
        run(db, monkeypatch, ["SELECT nope FROM orders"] * pipeline.MAX_ATTEMPTS)
    assert f"after {pipeline.MAX_ATTEMPTS} attempts" in err.value.message


# ---------- safety check ----------

@pytest.mark.parametrize(
    "sql",
    ["DROP TABLE orders", "SELECT 1; DELETE FROM orders", "PRAGMA table_info(orders)", "UPDATE orders SET amount = 0"],
)
def test_validator_blocks_writes(sql):
    with pytest.raises(UnsafeSQLError):
        validate_sql(sql)


def test_validator_allows_columns_that_contain_keywords():
    validate_sql("SELECT created_at, updated_on FROM t")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT REPLACE(name, 'a', 'b') FROM t",                # REPLACE() is a string function
        "SELECT * FROM t WHERE note = 'please update; then drop'",  # words inside a string literal
        'SELECT "Create Date" FROM t',                          # quoted identifier
    ],
)
def test_validator_allows_harmless_uses_of_keywords(sql):
    validate_sql(sql)


@pytest.mark.parametrize("sql", ["REPLACE INTO t VALUES (1)", "WITH x AS (SELECT 1) DELETE FROM t"])
def test_validator_still_blocks_statements(sql):
    with pytest.raises(UnsafeSQLError):
        validate_sql(sql)


# ---------- empty-result review ----------

def test_empty_result_is_sent_back_for_review(db, monkeypatch):
    events, calls = run(
        db, monkeypatch, ["SELECT name FROM customers WHERE city = 'kochi'", "SELECT name FROM customers WHERE city = 'Kochi'"]
    )
    attempts = events[-1]["response"]["trace"]["attempts"]
    assert attempts[0]["ok"] and attempts[0]["rows"] == 0 and "no rows" in attempts[0]["note"]
    assert "returned 0 rows" in calls[1]["history"][0][1]
    assert events[-1]["response"]["results"] == [["Asha Iyer"]]


def test_empty_result_review_only_happens_once(db, monkeypatch):
    events, calls = run(db, monkeypatch, ["SELECT name FROM customers WHERE city = 'Mars'"] * 2)
    assert len(calls) == 2  # reviewed once, then the empty answer is accepted
    assert events[-1]["response"]["results"] == []


def test_falls_back_to_the_empty_query_if_the_review_breaks_it(db, monkeypatch):
    first = "SELECT name FROM customers WHERE city = 'Mars'"
    events, _ = run(db, monkeypatch, [first, "SELECT nope FROM customers", "SELECT nope2 FROM customers"])
    assert events[-1]["response"]["sql"] == first


# ---------- value matching, descriptions, result review ----------

def test_value_links_fuzzy_match_for_a_misspelling(db):
    index = schema_linking.build_value_index(db, get_schema(db))
    found = value_links("Spending in New Dehli", index)
    assert any(v["value"] == "New Delhi" and v["match"] == "fuzzy" for v in found)


def test_value_links_partial_match_for_the_start_of_a_value(db):
    index = schema_linking.build_value_index(db, get_schema(db)) + [("customers", "city", "Riverside Unified")]
    found = value_links("Customers in Riverside", index)
    assert any(v["value"] == "Riverside Unified" and v["match"] == "partial" for v in found)


def test_category_columns_list_their_values(db):
    cats = schema_linking.category_values(schema_linking.build_value_index(db, get_schema(db)))
    assert cats[("products", "category")] == ["Electronics", "Furniture"]


def test_descriptions_are_read_and_shown(tmp_path):
    from app.agents.schema_agent import schema_to_text
    from app.database.descriptions import load_descriptions

    folder = tmp_path / "database_description"
    folder.mkdir()
    (folder / "schools.csv").write_text(
        "original_column_name,column_name,column_description,data_format,value_description\n"
        'SOC,School ownership code,,text,"66: High School"\n',
        encoding="utf-8-sig",
    )
    docs = load_descriptions(tmp_path / "db.sqlite")
    schema = {"tables": [{"name": "schools", "columns": [{"name": "SOC", "type": "TEXT", "primary_key": False}],
                          "foreign_keys": [], "sample_rows": []}]}
    assert "SOC TEXT -- School ownership code; values: 66: High School" in schema_to_text(schema, None, None, docs)


def test_result_review_feedback_triggers_a_revision(db, monkeypatch):
    events, calls = run(
        db, monkeypatch, ["SELECT name, city FROM customers", "SELECT name FROM customers"],
        review="Only the names were asked for; drop the city column.",
    )
    attempts = events[-1]["response"]["trace"]["attempts"]
    assert attempts[0]["note"].startswith("Result review: Only the names")
    assert "drop the city column" in calls[1]["history"][0][1]
    assert events[-1]["response"]["columns"] == ["name"]


def test_unchanged_query_after_review_is_accepted(db, monkeypatch):
    events, calls = run(db, monkeypatch, ["SELECT name FROM customers"] * 3, review="looks off")
    assert len(calls) == 2  # reviewed once; the model kept its query, so it is accepted
