-- Tenant-owned working-day and holiday rules for attendance reports.
CREATE TABLE IF NOT EXISTS tenant_attendance_calendar_settings (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    institute_id BIGINT NOT NULL,
    working_days VARCHAR(32) NOT NULL DEFAULT '0,1,2,3,4,5',
    created_at DATETIME NOT NULL,
    updated_at DATETIME NULL,
    UNIQUE KEY uq_tenant_attendance_calendar_institute (institute_id)
);

CREATE TABLE IF NOT EXISTS tenant_attendance_holidays (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    institute_id BIGINT NOT NULL,
    holiday_date DATE NOT NULL,
    title VARCHAR(255) NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NULL,
    UNIQUE KEY uq_tenant_attendance_holiday_date (institute_id, holiday_date)
);
