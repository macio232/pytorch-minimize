from setuptools import setup, find_packages

packages = [
    'numpy',
    'scipy',
    'torch'
]

setup(name='torchmin',
      version='0.0.2',
      description='Minimization for Pytorch',
      url='',
      author=' Reuben Feinman',
      author_email='',
      license='MIT Licence',
      packages=find_packages(),
	    zip_safe=False,
      install_requires=packages)
