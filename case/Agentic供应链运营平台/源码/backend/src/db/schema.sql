-- Products table
CREATE TABLE IF NOT EXISTS products (
    sku VARCHAR(50) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(100),
    unit_cost DECIMAL(10, 2) NOT NULL,
    reorder_point INTEGER NOT NULL,
    reorder_quantity INTEGER NOT NULL
);

-- Warehouses table
CREATE TABLE IF NOT EXISTS warehouses (
    warehouse_id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    location VARCHAR(255),
    capacity INTEGER NOT NULL
);

-- Inventory table
CREATE TABLE IF NOT EXISTS inventory (
    id SERIAL PRIMARY KEY,
    sku VARCHAR(50) REFERENCES products(sku),
    warehouse_id INTEGER REFERENCES warehouses(warehouse_id),
    quantity INTEGER NOT NULL DEFAULT 0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(sku, warehouse_id)
);

-- Vendors table
CREATE TABLE IF NOT EXISTS vendors (
    vendor_id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    contact_email VARCHAR(255),
    lead_time_days INTEGER NOT NULL DEFAULT 7,
    min_order_value DECIMAL(10, 2) NOT NULL DEFAULT 100.00
);

-- Vendor Products (pricing per vendor)
CREATE TABLE IF NOT EXISTS vendor_products (
    id SERIAL PRIMARY KEY,
    vendor_id INTEGER REFERENCES vendors(vendor_id),
    sku VARCHAR(50) REFERENCES products(sku),
    unit_price DECIMAL(10, 2) NOT NULL,
    discount_threshold INTEGER DEFAULT 100,
    discount_percent DECIMAL(5, 2) DEFAULT 0.00,
    UNIQUE(vendor_id, sku)
);

-- Sales History
CREATE TABLE IF NOT EXISTS sales_history (
    id SERIAL PRIMARY KEY,
    sku VARCHAR(50) REFERENCES products(sku),
    date DATE NOT NULL,
    quantity INTEGER NOT NULL,
    revenue DECIMAL(12, 2) NOT NULL
);

-- Purchase Orders
CREATE TABLE IF NOT EXISTS purchase_orders (
    po_id SERIAL PRIMARY KEY,
    vendor_id INTEGER REFERENCES vendors(vendor_id),
    sku VARCHAR(50) REFERENCES products(sku),
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(10, 2) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert sample data
INSERT INTO warehouses (name, location, capacity) VALUES
    ('Warehouse A - Chicago', 'Chicago, IL', 10000),
    ('Warehouse B - Dallas', 'Dallas, TX', 8000),
    ('Warehouse C - Phoenix', 'Phoenix, AZ', 6000)
ON CONFLICT DO NOTHING;

INSERT INTO products (sku, name, category, unit_cost, reorder_point, reorder_quantity) VALUES
    ('SKU-001', 'Industrial Bearing A', 'Mechanical', 45.00, 100, 500),
    ('SKU-002', 'Hydraulic Pump X', 'Hydraulics', 320.00, 50, 200),
    ('SKU-003', 'Steel Plate 10mm', 'Raw Materials', 120.00, 200, 1000),
    ('SKU-004', 'Circuit Board Z', 'Electronics', 85.00, 75, 300),
    ('SKU-005', 'Motor Assembly M', 'Motors', 560.00, 30, 100)
ON CONFLICT DO NOTHING;

INSERT INTO vendors (name, contact_email, lead_time_days, min_order_value) VALUES
    ('Acme Industrial', 'sales@acmeindustrial.com', 7, 500.00),
    ('Global Parts Co', 'orders@globalparts.com', 14, 250.00),
    ('Prime Materials Ltd', 'supply@primematerials.com', 10, 1000.00)
ON CONFLICT DO NOTHING;

INSERT INTO inventory (sku, warehouse_id, quantity) VALUES
    ('SKU-001', 1, 150),
    ('SKU-001', 2, 80),
    ('SKU-002', 1, 45),
    ('SKU-002', 2, 60),
    ('SKU-003', 1, 500),
    ('SKU-003', 3, 300),
    ('SKU-004', 2, 90),
    ('SKU-005', 1, 25)
ON CONFLICT DO NOTHING;

INSERT INTO vendor_products (vendor_id, sku, unit_price, discount_threshold, discount_percent) VALUES
    (1, 'SKU-001', 42.00, 200, 5.00),
    (1, 'SKU-002', 295.00, 100, 7.50),
    (1, 'SKU-003', 110.00, 500, 10.00),
    (2, 'SKU-001', 43.50, 150, 3.00),
    (2, 'SKU-004', 78.00, 100, 5.00),
    (2, 'SKU-005', 520.00, 50, 8.00),
    (3, 'SKU-003', 115.00, 400, 8.00),
    (3, 'SKU-005', 540.00, 75, 6.00)
ON CONFLICT DO NOTHING;

-- Sample sales history (last 90 days)
INSERT INTO sales_history (sku, date, quantity, revenue)
SELECT 
    p.sku,
    CURRENT_DATE - (i * INTERVAL '1 day'),
    floor(random() * 50 + 10)::integer,
    floor(random() * 50 + 10)::integer * p.unit_cost
FROM products p
CROSS JOIN generate_series(0, 89) AS i
ON CONFLICT DO NOTHING;
