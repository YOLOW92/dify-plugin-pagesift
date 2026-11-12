# Privacy Policy for PageSift Dify Plugin

This plugin connects Dify workflows to a self-hosted or dedicated PageSift instance.

## 1. Data Collection and Transmission
- **No Third-Party Telemetry**: The plugin transmits data exclusively to the PageSift base URL configured in your credentials. No telemetry, usage statistics, or analytics are collected or sent to any third-party endpoints.
- **Payload Handling**: Web scraping and document parsing payloads are processed strictly on demand to fulfill LLM pipeline operations.

## 2. Network and Security Controls
- **SSRF Prevention**: Built-in network validation blocks requests targeting RFC 1918 private subnets, loopback interfaces, link-local addresses, and cloud provider metadata services (e.g., 169.254.169.254).
- **Credential Protection**: API keys and authorization headers are sanitized and masked in application logs and trace messages.

## 3. Data Retention
- Neither the plugin wrapper nor the client library stores parsed content or uploaded files to persistent storage. All intermediate byte streams are processed in memory and released after invocation.

For inquiries or security reporting, contact the maintainer at `wyc610721@gmail.com`.
