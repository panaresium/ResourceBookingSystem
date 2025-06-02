import os
import json
from flask import request, g, has_request_context, current_app

# Determine basedir for translations.py, assuming it's in the project root.
# This means 'locales' directory is expected to be in the project root as well.
basedir = os.path.abspath(os.path.dirname(__file__))

class SimpleTranslator:
    def __init__(self, translations_dir='locales', default_locale='en'):
        # If config.py defines a BASEDIR, it might be better to pass it in.
        # For now, this assumes translations.py is at the root.
        self.translations_dir = os.path.join(basedir, translations_dir)
        self.default_locale = default_locale
        self.translations = {}
        self._load_translations()

    def _load_translations(self):
        if not os.path.isdir(self.translations_dir):
            # Consider logging a warning if the locales directory is not found.
            # print(f"Warning: Translations directory '{self.translations_dir}' not found.")
            return
        for fname in os.listdir(self.translations_dir):
            if fname.endswith('.json'):
                code = fname.rsplit('.', 1)[0]
                path = os.path.join(self.translations_dir, fname)
                with open(path, 'r', encoding='utf-8') as f:
                    try:
                        self.translations[code] = json.load(f)
                    except json.JSONDecodeError:
                        # Log error for specific file
                        # print(f"Error: Could not decode JSON from '{path}'.")
                        self.translations[code] = {}


    def gettext(self, text, lang=None):
        lang = lang or self.default_locale
        return self.translations.get(lang, {}).get(text, text)

translator = SimpleTranslator()

def get_locale():
    # Try to get language from query parameter first
    lang_query = request.args.get('lang')
    # Use current_app.config for accessing app configuration
    if lang_query and lang_query in current_app.config.get('LANGUAGES', ['en']):
        return lang_query

    # Fallback to Accept-Languages header
    return request.accept_languages.best_match(current_app.config.get('LANGUAGES', ['en']))

def _(text):
    # If in a request context, use get_locale(). Otherwise, use default.
    lang = get_locale() if has_request_context() else translator.default_locale
    return translator.gettext(text, lang)

# The following functions require the 'app' object for their decorators.
# They will be registered with the app in the app factory.

def set_locale():
    # g is request-specific, so it's fine here.
    g.locale = get_locale()

def inject_languages():
    # current_app.config is used here.
    return {'available_languages': current_app.config.get('LANGUAGES', ['en'])}

def init_translations(app):
    """
    Initializes and registers translation-related functions with the Flask app.
    This function will be called from the app factory.
    """
    app.jinja_env.globals['_'] = _

    # Register request handlers/context processors
    # These are moved from app.py and will be registered here.
    # The functions themselves are defined above.
    app.before_request(set_locale)
    app.context_processor(inject_languages)

    # Make translator instance available if needed, e.g. app.translator = translator
    # Or, ensure SimpleTranslator is initialized when this module is imported.
    # The current `translator = SimpleTranslator()` handles this.

    # Optionally, if SimpleTranslator needs app.config (e.g. for LANGUAGES for default_locale):
    # translator.init_app(app) # You would need to add an init_app method to SimpleTranslator

    # Log that translations are set up (optional)
    # app.logger.info("Translations system initialized.")
    pass
