-- =====================================================================
-- AI 模型配置表（AI 规范 §3.2 模型配置与版本管理 / §17.4 页面化模型配置）
-- @Author: 花海
-- @Date: 2026/08/17 15:00
-- @Description: 模型配置统一收敛于数据库（页面化配置新增/修改经 upsert 幂等落库），
--               模型逻辑名与供应商映射在 SPI 注册表声明、参数在此管理（规范 §3.2）；
--               api_key 列仅存 env:VAR 环境变量引用或配置中心密钥标识，
--               真实密钥由应用进程从环境变量/.env 注入，禁止明文落盘（规范 §3.1/AI-7）。
-- 说明：初始示例数据见 db/init/dml/002-ai-model-config-init-dml.sql。
-- =====================================================================

CREATE TABLE IF NOT EXISTS ai_model_config (
    id                  BIGINT PRIMARY KEY AUTO_INCREMENT,
    model_code          VARCHAR(128) NOT NULL COMMENT '模型逻辑名（唯一，业务引用标识）',
    model_name          VARCHAR(255) NOT NULL COMMENT '模型展示名',
    provider            VARCHAR(64)  NOT NULL DEFAULT 'openai_compatible' COMMENT '供应商逻辑名（协议，缺省 OpenAI 兼容）',
    api_base            VARCHAR(512) NOT NULL COMMENT '供应商 API 基地址',
    api_key             VARCHAR(512) NOT NULL COMMENT 'API Key 引用（env:VAR 或配置中心密钥标识，禁止明文落盘，规范 §3.1/AI-7）',
    model_id            VARCHAR(255) COMMENT '厂商侧真实模型 ID（缺省使用 model_code）',
    max_tokens          INT NOT NULL DEFAULT 4096 COMMENT '最大生成 Token 数',
    temperature         DECIMAL(6,2)  NOT NULL DEFAULT 0.00 COMMENT '采样温度',
    top_p               DECIMAL(6,2)  NOT NULL DEFAULT 0.00 COMMENT '核采样概率',
    timeout             INT NOT NULL DEFAULT 120 COMMENT '调用超时（秒）',
    is_deterministic    TINYINT NOT NULL DEFAULT 0 COMMENT '是否确定性生成（1 是）',
    stop                VARCHAR(1024) COMMENT '停止序列（JSON 数组或单字符串）',
    input_price_per_1k  DECIMAL(12,6) NOT NULL DEFAULT 0.000000 COMMENT '输入 Token 单价（元/1K，AI 规范 §5.2 成本计量）',
    output_price_per_1k DECIMAL(12,6) NOT NULL DEFAULT 0.000000 COMMENT '输出 Token 单价（元/1K）',
    created_at          DATETIME NOT NULL COMMENT '创建时间',
    updated_at          DATETIME COMMENT '更新时间',
    UNIQUE KEY uk_model_code (model_code),
    KEY idx_provider (provider)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = 'AI 模型配置表';
