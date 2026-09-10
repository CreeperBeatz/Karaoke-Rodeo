import uvicorn

from . import config

if __name__ == "__main__":
    print(f"{config.APP_NAME}  http://{config.HOST}:{config.PORT}/  data={config.DATA}  dev_mode={config.DEV_MODE}")
    uvicorn.run("server.main:app", host=config.HOST, port=config.PORT, proxy_headers=True, forwarded_allow_ips="*",
                log_level="info")
