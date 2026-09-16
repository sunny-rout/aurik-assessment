from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://monitoring:monitoring@localhost:5432/monitoring"
    redis_url: str = "redis://localhost:6379/0"

    pulseforge_api_key: str = "dev-pulseforge-key"
    thermexwatch_api_key: str = "dev-thermexwatch-key"
    maintaflow_api_key: str = "dev-maintaflow-key"

    reference_data_dir: str = "Aurik_Tech_Lead_Assessment_Assets"

    class Config:
        env_file = ".env"


settings = Settings()
