# Week 02 (10.26) | 云服务器与网站部署

**时间：** 2026.10.26  
**阶段：** Stage 0 - 搭建开发基础

## 一、做了什么

### 1. 购买并配置云服务器

- 购买阿里云轻量应用服务器（新加坡节点），先按月使用。
- **服务器配置：**
  - CPU：2 vCPU
  - RAM：1 GiB
  - Storage：30 GiB
  - OS：Ubuntu 24.04 LTS
  - Public IP：1 个 IPv4
- 选择海外节点，主要考虑后续 AI Agent 可能需要连接 Reddit、Amazon、YouTube 等海外平台。
- 暂时不在服务器本地运行大模型，后续计划通过 API 调用模型。

### 2. SSH Key 登录服务器

- 在阿里云控制台创建 SSH Key Pair，将公钥对应的密钥对绑定到服务器。
- 将下载的 `.pem` 私钥文件保存在 Mac 的 `~/.ssh/` 目录中。
- 设置私钥文件权限：

```bash
chmod 400 ~/.ssh/zhien-server.pem
```

- 通过 SSH 从 Mac 远程登录 Ubuntu：

```bash
ssh -i ~/.ssh/zhien-server.pem root@<服务器公网IP>
```

- 首次登录时确认服务器的 Host Key Fingerprint，并将其记录在本地 `known_hosts` 中。
- 成功使用 SSH Key 登录服务器，不需要输入服务器账户密码。

### 3. 安装 Nginx 并部署网站

在 Ubuntu 服务器中执行：

```bash
sudo apt update
sudo apt install nginx -y
sudo systemctl status nginx --no-pager
```

确认 Nginx 状态为 `active (running)`。

随后在浏览器中通过服务器公网 IP 访问，成功看到 Nginx 默认欢迎页面。

接着将 GitHub 仓库克隆到服务器：

```bash
cd /opt
git clone https://github.com/ZhienYu/AI-Marketing.git
```

找到网页文件的实际路径：

```text
/opt/AI-Marketing/网站/index.html
```

将其复制到 Nginx 的网站目录：

```bash
cp "/opt/AI-Marketing/网站/index.html" /var/www/html/index.html
```

刷新浏览器后，成功显示自己的个人网页。

### 4. 配置 DNS 与 HTTPS

在阿里云 DNS 控制台添加两条 A 记录：

| 主机记录 | 记录值 |
|---|---|
| @ | 服务器公网 IP |
| www | 服务器公网 IP |

成功通过 `http://zhienyu.com` 访问个人网页。

之后使用 Certbot 和 Let's Encrypt 免费证书配置 HTTPS：

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d zhienyu.com -d www.zhienyu.com --redirect
```

最终成功通过 **https://zhienyu.com** 访问个人网站，浏览器显示安全连接。

---

## 二、学了什么

### 1. 本地电脑与远程服务器的区别

- 通过 SSH 登录后，虽然命令是在 Mac 的 Terminal 中输入，但实际执行位置是远程 Ubuntu 服务器。
- 安装在服务器上的 Nginx 消耗的是云服务器的计算和内存资源，而不是 Mac 的 RAM。
- `exit` 可以退出 SSH，回到 Mac 本地终端。
- 关闭 Mac 或断开 SSH，并不代表云服务器和 Nginx 停止运行。

### 2. Nginx（Web Server）

Nginx 是 Web Server 软件，负责接收浏览器的 HTTP/HTTPS 请求，并返回网页文件。

这次使用的默认网站目录是：

```text
/var/www/html/
```

将 `index.html` 放到这个目录后，Nginx 就可以将网页提供给访问者。

**区别：** 云服务器是运行环境，Nginx 是运行在服务器上的软件。

### 3. GitHub 代码与线上网站不是自动同步的

这次使用的部署流程是：

```text
GitHub Repository
       ↓ git clone
Ubuntu Server
       ↓ cp
Nginx Website Directory
       ↓
Public Website
```

- `git clone`：将 GitHub 仓库下载到服务器。
- `cp`：将网页文件复制到 Nginx 的网站目录。
- 修改 GitHub 文件后，线上网站不会自动更新。
- 以后需要进一步学习 `git pull` 和自动化部署。

### 4. HTTPS 证书管理

- Let's Encrypt 可以提供免费的 TLS 证书。
- Certbot 可以帮助申请证书，并自动修改 Nginx 配置。
- `--redirect` 用于配置从 HTTP 跳转到 HTTPS。
- 证书需要定期续期，后续还要检查自动续期机制。

---

## 三、遇到的问题与解决方法

### 问题 1：SSH 第一次连接失败

**现象：** 首次连接时出现 Host Key 验证提示，确认后又遇到 `Connection closed`。

**解决：** 检查密钥绑定和服务器状态，重新连接后成功登录。

**学到：** SSH 主机身份验证与用户密钥登录是两个不同环节。看到服务器指纹验证提示，不代表已经成功登录。

### 问题 2：找不到 index.html

**现象：**

```text
No such file or directory
```

**原因：** 最开始以为 `index.html` 位于仓库根目录，实际文件位于 `网站` 子文件夹中。

**解决：** 使用 `ls -la` 查看服务器上的目录结构，找到正确路径后复制文件。

**学到：** 本地 Mac 与远程服务器有各自独立的文件系统；执行文件操作前，应先确认实际路径。

---

## 四、目前进度与下一步

**已完成：**

- [x] 云服务器购买与 Ubuntu 配置
- [x] SSH Key 远程登录
- [x] Nginx 安装与运行
- [x] GitHub 网站代码部署
- [x] 域名 DNS 解析
- [x] 网站 HTTPS 访问

**下一步：**

- [ ] 学习如何在修改 GitHub 代码后更新线上网站
- [ ] 开始 Stage 1：规划个人网站 v1，编写 PRD
- [ ] 完善个人简历、实习经历与项目展示页面

**本次最大的收获：** 第一次独立完成从购买云服务器、远程登录、安装 Web Server，到部署网页、绑定域名和配置 HTTPS 的完整过程。之前学习的概念真正变成了一个可以通过公网访问的网站。