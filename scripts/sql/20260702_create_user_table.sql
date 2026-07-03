-- 用户账号最小表结构。
-- 当前项目没有迁移框架，本脚本用于本地/开发库初始化或补齐字段。
-- password 按当前需求明文保存；生产环境必须改为密码哈希字段与认证体系。

CREATE SEQUENCE IF NOT EXISTS user_id_seq;

CREATE TABLE IF NOT EXISTS "user" (
    id integer PRIMARY KEY DEFAULT nextval('user_id_seq'),
    user_name varchar(255),
    password varchar(255)
);

ALTER SEQUENCE user_id_seq
    OWNED BY "user".id;

ALTER TABLE "user"
    ALTER COLUMN id SET DEFAULT nextval('user_id_seq');

ALTER TABLE "user"
    ADD COLUMN IF NOT EXISTS password varchar(255);

SELECT setval(
    'user_id_seq',
    COALESCE((SELECT MAX(id) FROM "user"), 0) + 1,
    false
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_user_name
    ON "user" (user_name);
