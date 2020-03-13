from Numbers import functions

factors = lambda n: [x for x in range(1, n + 1) if not n % x]
is_prime = lambda n: len(factors(n)) == 2
primefactors = lambda n: list(filter(is_prime, factors(n)))


def primefactorize(n):
    n = int(n)
    f = primefactors(n)
    if is_prime(n):
        return str(n)
    else:
        return str(f[0]) + "*" + primefactorize(n / f[0])


if __name__ == '__main__':
    print("Welcome to the Prime Factorizer.. Enter the numbers in the prompt or enter 'quit' to exit")
    num = 0

    while True:
        if num:
            print(primefactorize(num))
        print(">>>", end='')
        num = input()
        if num == 0:
            print("Factorization can not be done for 0")
            break
        if num.lower()[0] == "q":
            break
