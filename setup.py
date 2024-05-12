import setuptools
from bili_get import version

'''
python -m pip install --user --upgrade setuptools wheel
python setup.py sdist bdist_wheel
pip install dist\bili_get-0.0.1-py3-none-any.whl
'''

with open("readme.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setuptools.setup(
    name="bili_get",
    version=version,
    author="muggledy",
    author_email="zgjsycfndy2015@163.com",
    description="A simple tool to download videos from bilibili",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/muggledy/bili-get",
    packages=setuptools.find_packages(),
    python_requires=">=3.6",
    install_requires=[
        'requests',
    ],
    classifiers=[
        "License :: OSI Approved :: MIT License",
        'Operating System :: Microsoft :: Windows',
        'Operating System :: POSIX',
    ],
    exclude_package_data={
        '': ['__pycache__', 'log'],
    }
)