# 免费落地说明

当前最稳的免费公开试用路线：

1. GitHub 保存源码和版本。
2. Python 后端 + SQLite 保存账号、项目、模板和设置。
3. 邮箱密码注册登录免费可用，数据会按账号隔离。
4. 手机验证码不要在公网使用 `PHONE_CODE_DEV_MODE=1`；真实短信服务通常需要付费或实名接入。
5. 如果你已有免费 SMTP 邮箱，可以设置：

```env
EMAIL_VERIFICATION_MODE=smtp
EMAIL_SMTP_HOST=smtp.example.com
EMAIL_SMTP_PORT=587
EMAIL_SMTP_USER=your-account@example.com
EMAIL_SMTP_PASSWORD=your-smtp-password
EMAIL_FROM=your-account@example.com
```

未配置 SMTP 前保持 `EMAIL_VERIFICATION_MODE=off`。上线健康检查会提示“邮箱验证未启用”，但不会阻止邮箱密码登录。
