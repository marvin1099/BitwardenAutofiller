from setuptools import setup, find_packages

setup(
    name='BitwardenAutofiller',
    version='0.1.0',
    author='Your Name',
    author_email='your.email@example.com',
    description='A Bitwarden autofill script for non-browser applications',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/yourusername/bitwarden-autofiller',
    packages=find_packages(),  # Automatically finds all packages in the directory
    install_requires=[
        'clipboard',
        'pyautogui',
        'pywinctl',
        'psutil',
        'cryptography'
    ],
    entry_points={
        'console_scripts': [
            'bitwardenautofiller = main:main'
        ],
    },
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: AGPL3 License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.12',
)
