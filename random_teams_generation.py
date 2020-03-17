import random
from termcolor import colored

from tkinter import Tk
from tkinter.filedialog import askopenfilename

Tk().withdraw()  # we don't want a full GUI, so keep the root window from appearing
filelocation = askopenfilename()  # open the dialog GUI

l = []
f = open(filelocation, "r+")

for name in f:
    l = name.split(',')

for i in range(4):
    random.shuffle(l)

teams = []
for i in range(0, len(l), 2):
    teams.append(l[i:i + 2])

print(colored("\nTeams are as follows:\n", 'blue'))
for i in range(0, len(teams)):
    print(colored("Team {}: {} & {}".format(i + 1, teams[i][0], teams[i][1]), 'magenta'))

for i in range(4):
    random.shuffle(teams)

matches = []
for i in range(0, len(teams), 2):
    matches.append(teams[i:i + 2])

print(colored("\nMatches are as follows:\n", 'blue'))
for i in range(0, len(matches)):
    print(colored(
        "\nMatch {}: **{} & {}** Vs **{} & {}**".format(i + 1, matches[i][0][0], matches[i][0][1], matches[i][1][0],
                                                        matches[i][1][1]), 'green'))
