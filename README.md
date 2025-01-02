## Overview


## Setting up the Bot

To setup the bot
1. Install Python 3.10+, the pip Python package manager and the Python virtual environment module.
```bash

```

2. Create a Python virtual environment called "venv".
```bash

```

3. Activate the virtual environment. (Note: Every time you run the bot you'll need to make sure you're inside the virtual environment by running this command. You can confirm it was successful by noticing your terminal prefix has changed to "venv")
```bash
pipenv shell
pipenv install
```

4. Install dependencies into the virtual environment.
```bash
pip3 install discord.py python-dotenv requests
```

7. Create a .env file that contains the bot's token and a data.json file that contains the data required for the bot to work. See below for the format of these files.

8. Run the bot.
```bash
python .\main.py
```

## Files

- `.env`
```
 DISCORD_TOKEN=<Discord Bot Token>
 STEAM_KEY=<Steam Key>
 X_SUPER_PROPERTIES=<Valid Discord super properties of bot>
```