# -*- coding: utf-8 -*-

import os
from dotenv import load_dotenv
load_dotenv(dotenv_path=".env", verbose=True)


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "devsk")
    GA_KEY = os.environ.get('GA_KEY')
    RECAPTCHA_PUBLIC_KEY = os.environ.get('RECAPTCHA_KEY')
    RECAPTCHA_PRIVATE_KEY = os.environ.get('RECAPTCHA_SECRET')
    BABEL_DEFAULT_LOCALE = 'en'
    EMAIL_FROM = os.getenv('EMAIL_FROM', 'noreply@ksvotes.org')
    EMAIL_BCC = os.getenv('EMAIL_BCC', 'registration@ksvotes.org')
    AWS_DEFAULT_REGION = os.getenv('AWS_DEFAULT_REGION')
    SES_ACCESS_KEY_ID = os.getenv('SES_ACCESS_KEY_ID')
    SES_SECRET_ACCESS_KEY = os.getenv('SES_SECRET_ACCESS_KEY')
    SEND_EMAIL = os.getenv('SEND_EMAIL')
    SSL_DISABLE = os.getenv('SSL_DISABLE', False)
    SESSION_TTL = os.getenv('SESSION_TTL', '10')
    DEMO_UUID = os.getenv('DEMO_UUID', None)
    ENABLE_AB = os.getenv('ENABLE_AB', False)
    ENABLE_AB_TRACKER = os.getenv('ENABLE_AB_TRACKER', False)
    ENABLE_VOTING_LOCATION = os.getenv('ENABLE_VOTING_LOCATION', False)
    FAIL_EMAIL = os.getenv('FAIL_EMAIL', 'fail@ksvotes.org')
    STAGE_BANNER = os.getenv('STAGE_BANNER', False)

    @staticmethod
    def init_app(app):
        pass


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SEND_EMAIL = False


class ProductionConfig(Config):
    JSONIFY_PRETTYPRINT_REGULAR = False


config = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig
}

LANGUAGES = {
    'en': 'English',
    'es': 'Español'
}
