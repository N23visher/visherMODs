# visher MODs
战舰世界MOD本地化管理工具

## 功能
1.自动检测游戏路径
2. 本地仓库管理
   - mod以ZIP格式导入，自动识别content、PnF
   - 对结构不完整的MOD压缩包，弹窗选择MOD类型，自动补全目录层级
   - MOD列表支持搜索（仅中文匹配）
   - MOD批量勾选安装
   - 支持删除本地仓库内的MOD压缩包
3. 线上仓库
   - 从github、gitee拉取MOD清单，一键下载至本地仓库
4. MOD类型区分：content mod、PnF mod

## 注意：
- 本工具仅做文件复制，不修改游戏本体程序
- 卸载前注意备份游戏mod相关文件，卸载同时会将本地仓库清空（工具自带的文件夹）
## 仅供个人学习娱乐使用 ##

## 运行
- 运行`main.py`需要Python3环境
- 可使用PyInstaller打包为exe程序，搭配Inno‑Setup制作安装程序

## License
GUN General Public License v3.0
