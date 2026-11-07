-- Apply after 20261029_cashfree_sandbox.sql in the intended test database.
-- Stores only a digest of the signed link, never the bearer link itself.
CREATE TABLE IF NOT EXISTS cashfree_payment_link_orders (
    order_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    link_digest VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    payment_option VARCHAR(16) NOT NULL,
    created_at VARCHAR(32) NOT NULL,
    CONSTRAINT fk_cashfree_link_order FOREIGN KEY (order_id)
        REFERENCES cashfree_orders(order_id) ON DELETE RESTRICT,
    CONSTRAINT chk_cashfree_link_option CHECK (payment_option IN ('full', 'installment'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Preserve this mapping when rolling back application code.
