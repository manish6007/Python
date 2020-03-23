import random
faces = ('Head','Tail')
def funcproc():
    return random.choice(faces)
    
for flipcoin in range(5):
    print(funcproc(), end=' ')
print()

def iadd(arg1, arg2):
    '''Perform inline + operations'''
    return arg1 + arg2

print('iadd(3, 5)-->',iadd(3, 5))
print('iadd("dy", "namic")-->',iadd("dy", "namic"))

def isum(*args):
    '''Return of total of numeric arguments'''
    print('args-->', args)
    total = 0
    for arg in args:
        total += arg
    return total
    
print('isum(1,2,3,4,5)-->',isum(1,2,3,4,5))
params = (1,2,3,4,5)
print('isum(*params)-->',isum(*params))

def ilist(alpha, beta='default', gamma='assumed'):
    return alpha, beta, gamma
    
print('ilist("required")-->',ilist("required"))

alphabet = {'alpha':'α', 'beta':'β','gamma':'γ'}

print('ilist(**alphabet)-->',ilist(**alphabet))

def iflex(**kwargs):
    print('kwargs -->', kwargs)
    for key in kwargs:
        print(key, '->', kwargs[key])
    return tuple(kwargs.values())

alphabet = {}
print('iflex(**alphabet) -->', iflex(**alphabet))
alphabet = {'alpha':'α', 'beta':'β','gamma':'γ'}
print('iflex(**alphabet) -->', iflex(**alphabet))
