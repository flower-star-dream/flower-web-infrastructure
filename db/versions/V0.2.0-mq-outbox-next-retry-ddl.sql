-- =====================================================================
-- Outbox 增量脚本（示例）：新增 next_retry_at 列（规范 §13.2 / S9-4 指数退避）
-- @Author: 花海
-- @Date: 2026/08/15 10:00
-- @Description: 示例增量 DDL（db/versions/）：message_outbox 增加"下次可重试时间"列，
--               与 OutboxPublisher 指数退避语义（S9-4，mark_failed 写入）对齐。
--               基线脚本 db/init/ddl/001-mq-init-ddl.sql 不含此列（基线不可回改），
--               通过本版本脚本增量演进；配套 DML 见同版本 -dml.sql。
-- 说明：本文件为版本增量脚本示例，演示命名规范 V{版本号}-模块-{变更描述}-ddl.sql
--       与"禁止回改基线、只允许新增版本脚本"的演进规则。
-- =====================================================================

ALTER TABLE message_outbox
    ADD COLUMN next_retry_at DATETIME NULL
        COMMENT '下次可重试时间（指数退避 base*2^retry_count，S9-4；NULL 表示无需退避）'
        AFTER retry_count;
