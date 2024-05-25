import setuptools, platform
from sole_bili_get import __version__, __name__

'''
https://blog.csdn.net/weixin_44015805/article/details/101076449
https://cloud.tencent.com/developer/article/2114297
python -m pip install --user --upgrade setuptools wheel
python setup.py sdist bdist_wheel
pip install dist\sole_bili_get-0.0.1-py3-none-any.whl
pip show bili_get
from bili_get import Bilibili
bili-get --help
'''

with open("readme.md", "r", encoding="utf-8") as f:
    long_description = f.read()

install_requires_common = [
    'requests',
]
install_requires_windows = install_requires_common + [
    'pycryptodome', 'pypiwin32',
]
install_requires_linux = install_requires_common + []

if platform.system() == 'Windows':
    install_requires = install_requires_windows
else:
    install_requires = install_requires_linux

setuptools.setup(
    name=__name__,
    version=__version__,
    author="muggledy",
    author_email="zgjsycfndy2015@163.com",
    description="A simple tool to download videos from bilibili{*≧∀≦}",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/muggledy/bili-get",
    license="MIT",
    packages=setuptools.find_packages(),
    python_requires=">=3.6",
    install_requires=install_requires,
    classifiers=[
        "License :: OSI Approved :: MIT License",
        'Operating System :: Microsoft :: Windows',
        'Operating System :: POSIX',
    ],
    exclude_package_data={
        'bili_get': ['__pycache__', 'log'],
    },
    entry_points={
        'console_scripts': [
            'bili-get = sole_bili_get:main',
        ],
    }
)