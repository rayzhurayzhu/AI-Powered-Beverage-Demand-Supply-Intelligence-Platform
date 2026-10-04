# Step 4 Validation — 2026-10-04

## Executed in the authoring environment

- Generated all transactions using the original Step 3 master-data values and the successfully extracted public-holiday snapshot from Step 1.
- Produced 18,072 sales rows, 6,024 inventory rows and 770 purchase-order lines, including 20 open lines at the cutoff.
- Verified unique grains, exact Decimal revenue arithmetic, nonnegative/continuous inventory, sales-to-inventory reconciliation, PO-to-inventory receipt reconciliation, MOQ/case multiples, supplier mapping, and receipt/cutoff timing.
- Re-generated the data with the same inputs and confirmed identical transaction objects.
- Injected incorrect inventory, sales and PO quantities and confirmed validation rejected them.
- Checked the five reconciliation result sets on an in-memory SQLite database populated with the generated CSVs, adapting MySQL DATE_SUB syntax. All eleven audit counts were zero, the snapshot had six rows, and open orders had twenty rows. This checks query logic, not MySQL schema compatibility.
- Exercised the loader's failure path with a mocked connection and confirmed rollback without a data-refresh commit.

## Not executed here

No real MySQL Server was available in the authoring environment. Schema creation, foreign keys, CHECK constraints, connector serialization and live MySQL transactions must be accepted locally. SQLite and mock checks are not MySQL integration tests.

## Local acceptance

1. Run `sql/04_create_transaction_tables.sql` with no SQL errors.
2. Run the Python generator/loader and confirm `TRANSACTION PIPELINE OK`.
3. Run `sql/05_verify_transactions.sql` and confirm expected row counts and all eleven audit counts equal zero.
4. Inspect the six-SKU as-of snapshot and the open-order list.
5. A later rerun with unchanged inputs should preserve row counts; it refreshes only beverage_demo_v1.

PO counts can change with different master parameters, holiday inputs or runtime details. Match local database counts to the local generator log and manifest rather than forcing the authoring example count.

## Official implementation references

- [MySQL Connector/Python executemany](https://dev.mysql.com/doc/connector-python/en/connector-python-api-mysqlcursor-executemany.html)
- [MySQL window functions](https://dev.mysql.com/doc/refman/8.0/en/window-function-descriptions.html)
- [MySQL foreign keys](https://dev.mysql.com/doc/refman/8.0/en/create-table-foreign-keys.html)
- [MySQL CHECK constraints](https://dev.mysql.com/doc/refman/8.0/en/create-table-check-constraints.html)
