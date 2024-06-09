import setuptools
from sole_bili_get import __version__, __name__

'''
python setup.py develop
python setup.py develop --uninstall
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
    install_requires=[
        'requests', 'colorama', 'psutil',
        'pycryptodome; platform_system == "Windows"',
        'pypiwin32; platform_system == "Windows"',
    ],
    classifiers=[
        "License :: OSI Approved :: MIT License",
        'Operating System :: Microsoft :: Windows',
        'Operating System :: POSIX',
    ],
    exclude_package_data={
        'bili_get': ['__pycache__', ],
    },
    entry_points={
        'console_scripts': [
            'bili-get = sole_bili_get:main',
        ],
    }
)