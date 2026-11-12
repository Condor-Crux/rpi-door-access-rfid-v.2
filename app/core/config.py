from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    SUPER_USER: str = "admin"
    SUPER_PASSWORD: str
    VERBOSE: bool = False
    JWT_SECRET_KEY: str = "secret"
    DATABASE_URL: str = "sqlite:///./rpi_door_access.db"
    
    # GPIO Pins (from ADR docs/GPIO.jpeg)
    RELAY_PIN: int = 17
    BUZZER_PIN: int = 22
    LED_GREEN_PIN: int = 27
    LED_RED_PIN: int = 18
    # RFID uses SPI and RST 25
    RFID_RST_PIN: int = 25

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding='utf-8', extra='ignore')

settings = Settings()
