#!/bin/bash

# Assegna i permessi di esecuzione allo script
chmod +x "$0"

# Inizializza la configurazione di Conda nel tuo shell
eval "$(conda shell.bash hook)"

# Creazione dell'ambiente conda da environment.yaml
conda env create -f environment.yaml

# Attivazione dell'ambiente conda
conda activate vista_env

# Creazione dell'ambiente conda da environment.yaml
xargs -L 1 pip install < requirements.txt

# Installazione del package da GitHub utilizzando pip
pip install git+https://github.com/MattiaMarseglia/vista.git

