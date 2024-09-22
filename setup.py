from setuptools import setup, find_packages

setup(
    name='BitwardenAutofiller',
    version='0.1.0',
    author='marvin1099',
    description='A Bitwarden autofill script for non-browser applications',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://codeberg.org/marvin1099/BitwardenAutofiller',
    packages=find_packages(),
    install_requires=[
        'clipboard',
        'pyautogui',
        'pywinctl',
        'psutil',
        'cryptography'
    ],
    entry_points={
        'console_scripts': [
            'bitwardenautofiller = bitwardenautofiller:main'
        ],
    },
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: AGPL3 License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.12',
)
