# Git 新手超详细教程：从 Gitee 创建仓库到本地推送代码

本教程面向纯新手，全程手把手实操，覆盖 **安装Git→Gitee建仓库→本地初始化→提交推送** 完整流程，适用于 Windows/Mac 系统，零基础可直接跟着做。

## 一、前期准备：安装 Git

### 1\. 下载安装

官网下载：[https://git\-scm\.com/](https://git-scm.com/)

安装注意：全程默认下一步即可，无需修改配置，新手不要自定义参数。

### 2\. 验证安装是否成功

鼠标右键桌面/任意文件夹，选择 **Git Bash Here** 打开终端，输入命令：

```Plain Text
git --version
```

输出 git 版本号（如 git version 2\.45\.1）即安装成功。

### 3\. 配置全局用户名和邮箱（关键！只需要配置一次）

这里的用户名、邮箱 **必须和你的 Gitee 账号一致**

```Plain Text
# 配置用户名（Gitee昵称/账号名）
git config --global user.name "你的Gitee用户名"

# 配置邮箱（Gitee绑定的邮箱）
git config --global user.email "你的Gitee邮箱"
```

查看配置是否生效：

```Plain Text
git config --global --list
```

## 二、Gitee 官网创建代码仓库

### 1\. 登录 Gitee

打开 [https://gitee\.com/](https://gitee.com/)，登录自己的账号。

### 2\. 新建仓库

1\. 点击右上角 **\+ 号** → 新建仓库

2\. 填写仓库核心信息：

- **仓库名称**：自定义（英文/小写/无空格，例如 test\-demo）

- **仓库介绍**：可选填

- **是否公开**：根据需求选择（公开/私有）

- **初始化仓库**：**不要勾选！！！**（新手必避坑，勾选会导致本地和远程冲突）

3\. 点击 **创建**，创建完成后会进入仓库主页。

### 3\. 复制仓库 HTTPS 地址

仓库创建成功后，页面会显示克隆地址，选择**HTTPS** 模式，复制链接（全程用HTTPS，新手不用SSH）。

示例链接格式：https://gitee\.com/你的用户名/仓库名\.git

## 三、本地项目关联 Gitee 仓库并推送

提前准备：新建一个本地项目文件夹（例如 my\-git\-project），放入你的代码/文件。

### 1\. 打开 Git 终端

进入项目文件夹，空白处右键 → **Git Bash Here**

### 2\. 初始化本地 Git 仓库

首次使用必须初始化，让文件夹被 Git 管理：

```Plain Text
git init
```

执行后文件夹会生成隐藏的 \.git 文件夹（系统文件，不用管）。

### 3\. 将本地文件添加到暂存区

```Plain Text
# 添加所有文件到暂存区
git add .
```

说明：`git add .` 代表添加当前文件夹下所有文件，新手统一用这个即可。

### 4\. 本地提交代码（必须写提交说明）

```Plain Text
git commit -m "第一次提交：初始化项目文件"
```

引号内为自定义备注，用于记录本次提交的内容，不能为空。

### 5\. 关联远程 Gitee 仓库

替换成你刚刚复制的 Gitee 仓库 HTTPS 链接：

```Plain Text
git remote add origin 你的Gitee仓库HTTPS链接
```

示例：

```Plain Text
git remote add origin https://gitee.com/xxx/test-demo.git
```

查看是否关联成功：

```Plain Text
git remote -v
```

### 6\. 本地代码推送到 Gitee 远程仓库

首次推送必须指定分支（默认主分支为 master）：

```Plain Text
git push -u origin master
```

### 7\. 输入 Gitee 账号密码

执行推送命令后，弹窗提示输入：

- 用户名：Gitee 登录账号

- 密码：**Gitee 个人访问令牌（重点）**

> **新手必看：现在 Gitee 已不支持原生密码推送，必须用令牌！**
> 
> 获取令牌步骤：Gitee 主页 → 右上角头像 → 设置 → 私人令牌 → 生成新令牌 → 勾选所有权限 → 复制令牌（只显示一次，务必保存）
> 
> 

输入完成后，回车，推送成功！

## 四、后续日常更新代码推送（重复操作）

首次关联完成后，后续修改文件推送只需3步，无需重复初始化、关联仓库：

```Plain Text
# 1. 添加所有修改的文件
git add .

# 2. 本地提交，填写修改说明
git commit -m "更新：修复xxx问题/新增xxx功能"

# 3. 推送到远程仓库
git push
```

## 五、常见报错与解决方案（新手高频坑）

### 1\. 报错：fatal: remote origin already exists

原因：已经关联过远程仓库

解决：删除旧关联，重新关联

```Plain Text
git remote remove origin
```

### 2\. 推送失败、权限不足

原因：使用了登录密码，未使用私人令牌

解决：重新输入 **Gitee 私人令牌** 作为密码

### 3\. 本地远程代码冲突

原因：远程仓库有文件，本地为空（新建仓库勾选了初始化）

解决：强制拉取远程代码合并

```Plain Text
git pull origin master --allow-unrelated-histories
```

## 六、核心命令总结（收藏备用）

```Plain Text
# 初始化仓库
git init
# 添加所有文件
git add .
# 本地提交
git commit -m "备注"
# 关联远程仓库
git remote add origin 仓库地址
# 首次推送
git push -u origin master
# 日常推送
git push
# 查看远程关联
git remote -v
```
