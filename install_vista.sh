#!/bin/bash

# Assegna i permessi di esecuzione allo script
chmod +x "$0"

# Creazione dell'ambiente conda da environment.yaml
conda env create -f environment.yaml

# Attivazione dell'ambiente conda
conda activate vista_env

# Installazione del package da GitHub utilizzando pip
pip install git+https://github.com/MattiaMarseglia/vista.git
