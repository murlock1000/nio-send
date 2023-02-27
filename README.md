# nio-send 
[![Built with nio-template](https://img.shields.io/badge/built%20with-nio--template-brightgreen)](https://github.com/anoadragon453/nio-template)

A Matrix bot application for queueing message tasks and sending them to encrypted rooms.

This bot is designed to create message tasks to be sent to an existing or new encrypted user room.
If no common room exists with the user, a new room is created. The messages are put into a queue to be sent when room encryption completes.
All of the queued message tasks are sent with respect to message throttling. 
The main loop exits once all of the messages have been sent.


# Getting started

## Setup environment

### Install environment dependencies
Install libolm:
`sudo apt install libolm-dev`

Install python dev tools
`sudo apt-get install python3-dev`

Install build essentials
`sudo apt-get install build-essential`

Install postgres development headers (optional):
`sudo apt install libpq-dev libpq5`

### Create a virtual environment

`virtualenv -p python3 env`
Activate the venv
`source env/bin/activate`

### Install python dependencies

`pip install -e.`

(Optional) install postgres python dependencies:
`pip install -e ".[postgres]"`


## Project Configuration

### Setup configuration file

Copy sample config file to new 'config.yaml' file
`cp sample.config.yaml config.yaml`

Configure the file with appropriate settings


## Running the project

Try sending the preconfigured messages to a user (username does not require @:hostname - added based on values in `config.yaml`)
`python nio-send config.yaml ./example/toads.jpg test`


# Useful resources for working with Matrix

* A template for creating bots with
[matrix-nio](https://github.com/poljar/matrix-nio).
* The documentation for [matrix-nio](https://matrix-nio.readthedocs.io/en/latest/nio.html).
* Matrix Client-Server API [documentation](https://matrix.org/docs/api/#overview) (also allows configuring and sending events)




