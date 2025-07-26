from setuptools import setup, find_packages

setup(
    name="watermarker",
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_requires=[
        'fastapi>=0.68.0',
        'uvicorn>=0.15.0',
        'python-multipart>=0.0.5',
        'python-dotenv>=0.19.0',
        'pydantic>=1.8.0',
        'python-magic>=0.4.24',
    ],
    entry_points={
        'console_scripts': [
            'watermarker=watermarker.cli:main',
        ],
    },
    python_requires='>=3.10',
    include_package_data=True,
)
