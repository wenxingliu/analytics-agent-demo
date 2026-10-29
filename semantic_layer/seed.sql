-- Builds the demo database (SQLite). Deterministic, so results are repeatable.
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    full_name   TEXT NOT NULL,
    email       TEXT NOT NULL,
    country     TEXT NOT NULL,
    signup_date DATE NOT NULL,
    is_test     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    category   TEXT NOT NULL,
    price      DECIMAL(10,2) NOT NULL
);

CREATE TABLE orders (
    order_id     INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date   DATE NOT NULL,
    status       TEXT NOT NULL,
    total_amount DECIMAL(12,2)
);

CREATE TABLE order_items (
    order_id   INTEGER NOT NULL REFERENCES orders(order_id),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    quantity   INTEGER NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    PRIMARY KEY (order_id, product_id)
);

WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 60)
INSERT INTO customers
SELECT i,
       'Customer ' || i,
       'customer' || i || '@example.com',
       CASE i % 4 WHEN 0 THEN 'Canada' ELSE 'US' END,
       date('2024-06-01', '+' || (i * 9) || ' days'),
       CASE WHEN i > 57 THEN 1 ELSE 0 END
FROM n;

INSERT INTO products (product_id, name, category, price) VALUES
    (1, 'Ceramic Mug', 'Kitchen', 12.50),
    (2, 'Cast Iron Pan', 'Kitchen', 49.00),
    (3, 'Chef Knife', 'Kitchen', 79.90),
    (4, 'Linen Napkins', 'Kitchen', 18.00),
    (5, 'Wool Throw', 'Living Room', 64.00),
    (6, 'Table Lamp', 'Living Room', 55.00),
    (7, 'Floor Rug', 'Living Room', 149.00),
    (8, 'Wall Clock', 'Living Room', 35.00),
    (9, 'Picture Frame', 'Decor', 15.00),
    (10, 'Scented Candle', 'Decor', 22.00),
    (11, 'Vase', 'Decor', 28.50),
    (12, 'Plant Pot', 'Decor', 17.00),
    (13, 'Duvet Cover', 'Bedroom', 89.00),
    (14, 'Pillow Set', 'Bedroom', 45.00),
    (15, 'Bedside Table', 'Bedroom', 120.00),
    (16, 'Bath Towels', 'Bathroom', 38.00),
    (17, 'Soap Dispenser', 'Bathroom', 14.00),
    (18, 'Shower Curtain', 'Bathroom', 26.00),
    (19, 'Storage Basket', 'Storage', 32.00),
    (20, 'Shelf Unit', 'Storage', 135.00);

WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 800)
INSERT INTO orders (order_id, customer_id, order_date, status)
SELECT i,
       (i * 37) % 60 + 1,
       date('2025-01-01', '+' || ((i * 7) % 660) || ' days'),
       CASE i % 20
           WHEN 0 THEN 'cancelled'
           WHEN 1 THEN 'refunded'
           WHEN 2 THEN 'shipped'
           WHEN 3 THEN 'shipped'
           WHEN 4 THEN 'pending'
           ELSE 'delivered'
       END
FROM n;

WITH RECURSIVE k(j) AS (SELECT 1 UNION ALL SELECT j + 1 FROM k WHERE j < 3)
INSERT INTO order_items
SELECT o.order_id, p.product_id, (o.order_id + k.j) % 3 + 1, p.price
FROM orders o
JOIN k ON k.j <= o.order_id % 3 + 1
JOIN products p ON p.product_id = (o.order_id * 7 + k.j * 6) % 20 + 1;

UPDATE orders
SET total_amount = (
    SELECT ROUND(SUM(quantity * unit_price) * 1.08, 2)
    FROM order_items i WHERE i.order_id = orders.order_id
);
