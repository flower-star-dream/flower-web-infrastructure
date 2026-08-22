-- =====================================================================
-- V0.2.0-search-sync-offset-ddl.sql：CDC 位点存储表增量（搜索引擎数据同步方案 §5.3）
-- @Author: 花海
-- @Date: 2026/08/22 16:00
-- @Description: CDC 断点续传位点持久化表：source/db/table 组合主键，value 为数据源位点字符串
--               （MySQL 为 "log_file:log_pos"）。save 为幂等覆盖（先查后写），load 无记录返回 None
--               （数据源从当前位置起读，位点丢失走空闲对账兜底）。
-- 说明：新表无初始数据（DML 无需提供）；位点由 MysqlOffsetStore 运行时写入，无需种子数据。
-- =====================================================================

CREATE TABLE IF NOT EXISTS web_search_sync_offset (
    source        VARCHAR(64)  NOT NULL COMMENT '数据源标识（如 mysql）',
    database_name VARCHAR(128) NOT NULL COMMENT '数据库名',
    table_name    VARCHAR(128) NOT NULL COMMENT '表名（位点聚合粒度，通常为 offset 占位）',
    position      VARCHAR(255) NOT NULL COMMENT '位点字符串（如 binlog.000123:456789）',
    updated_at    DATETIME     NOT NULL COMMENT '最近更新时刻（CURRENT_TIMESTAMP 写入）',
    PRIMARY KEY (source, database_name, table_name)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = 'CDC 同步位点存储表';
