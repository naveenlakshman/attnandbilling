CREATE TABLE IF NOT EXISTS lms_batch_topic_progress (
    id INT AUTO_INCREMENT PRIMARY KEY,
    batch_id INT NOT NULL,
    program_id INT NOT NULL,
    master_topic_id INT,
    topic_id INT,
    taught_by_user_id INT NOT NULL,
    taught_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_lms_batch_topic_progress_batch_topic (batch_id, program_id, master_topic_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
