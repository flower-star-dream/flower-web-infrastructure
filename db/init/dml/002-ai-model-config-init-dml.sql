-- =====================================================================
-- AI 模型配置表基线 DML（初始示例模型）
-- @Author: 花海
-- @Date: 2026/08/17 15:00
-- @Description: 初始默认模型（deepseek-v4-flash，OpenAI 兼容协议）。
--               api_key 列仅存 env:LLM_API_KEY 环境变量引用，禁止明文 SQL——
--               真实密钥在部署环境 .env 中配置（如 LLM_API_KEY=sk-xxx），
--               应用运行时经 ModelConfig.resolved_api_key 从环境变量解析（AI 规范 §3.1/AI-7）。
--               幂等：INSERT IGNORE 按 model_code 唯一键去重，重复执行不覆盖已修改的配置。
-- =====================================================================

INSERT IGNORE INTO ai_model_config (
    model_code, model_name, provider, api_base, api_key, model_id,
    max_tokens, temperature, top_p, timeout, is_deterministic, stop,
    input_price_per_1k, output_price_per_1k, created_at, updated_at
) VALUES (
    'deepseek-v4-flash', 'DeepSeek V4 Flash', 'openai_compatible',
    'https://api.deepseek.com/v1', 'env:LLM_API_KEY', 'deepseek-v4-flash',
    4096, 0.00, 0.00, 120, 0, NULL,
    0.000000, 0.000000, NOW(), NOW()
);
