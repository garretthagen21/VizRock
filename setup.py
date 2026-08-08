#!/usr/bin/env python

from setuptools import setup, find_packages

setup(name='VizRock',
      version='1.0.0',
      author='Garrett Hagen',
      author_email='garretthagen21@gmail.com',
      description='Show Brain live control appliance for VizRock',
      long_description=open('README.md').read(),
      url='https://github.com/garretthagen21/VizRock.git',
      packages=find_packages(),
      package_data={'show_brain': ['interface/web/*']},
      python_requires='>=3.10',
      entry_points={
          "console_scripts": [
              "showbrain_run = show_brain.__main__:run",
              "showbrain_test = show_brain.test.test_runner:main"
          ]
      },
      # lower bounds, not pins: the exact pins forced a source build on any newer
      # Python, and pip should be free to pick a prebuilt wheel for whatever the
      # OS ships. See CLAUDE.md for the Bookworm/Trixie situation.
      install_requires=[
          'mido>=1.3.2',
          'python-rtmidi>=1.5.8',
          'pyserial>=3.5',
          'aiohttp>=3.9.5',
          'luma.oled>=3.13.0',
          'Pillow>=10.0'
      ])
