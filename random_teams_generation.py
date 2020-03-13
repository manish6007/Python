import random

l = []
f = open("player_list.txt", "r+")

for name in f:
    l = name.split(',')

for i in range(4):
    random.shuffle(l)

teams = []
for i in range(0,  len(l), 2):
    teams.append(l[i:i + 2])

for i in range(0, len(teams)):
    print("Team {}: {} & {}".format(i, teams[i][0],teams[i][1]))
