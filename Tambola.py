
from random import randint
tamb = []


def tambola():
    x = randint(1, 100)
    # print(x)
    return x


def gen_number():
    x = tambola()
    if x not in tamb:
        tamb.append(x)
        print(x)
    elif len(tamb)==100:
        print("All the number are covered on board")


from tkinter import *

window = Tk()
window.title("Tambola Number Generator")
button = Button(window, text="Tambola", command=gen_number)
button.pack()
window.mainloop()
