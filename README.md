# 配置项目  当前开发版本：Python3.14
pip install -e .

## 含义 ： e ditable（可编辑模式）

- 生产模式（FastAPI 直接托管前端静态资源）
  
  - 在 c:\Project\AITools\webui ：编译前端静态资源
    - npm install
    - npm run build
  - 在 c:\Project\AITools ：
    - python Mission_MultiAgent\Mission2_WebUI_FastAPI.py --host 127.0.0.1 --port 8766
  - 浏览器打开： http://127.0.0.1:8766/
- 开发模式（Vite 热更新）

  - 后端同上先启动（8766）
  - 在 c:\Project\AITools\webui ：
    - npm run dev
  - 打开 http://localhost:5173/ （已自动代理 /api 到 8766）

  - 打包 exe（不包含 config）：
  ```
  cd c:\Project\AITools
  pyinstaller --noconfirm --onefile --name AITools 
  --add-data="webui\dist:webui\dist" --collect-submodules src 
  --collect-submodules fastapi --collect-submodules uvicorn 
  src\fast_api.py
  ```