from setuptools import setup

APP = ['window_layout.py']
OPTIONS = {
    'argv_emulation': False,
    'iconfile': 'WindowLayout.icns',
    'plist': {
        'LSUIElement': True,
        'CFBundleName': 'WindowLayout',
        'CFBundleIdentifier': 'com.gesm.windowlayout',
        'CFBundleShortVersionString': '1.0.0',
    },
    'packages': ['objc', 'AppKit', 'Quartz'],
}

setup(
    app=APP,
    name='WindowLayout',
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
