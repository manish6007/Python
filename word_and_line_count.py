class file_stats:

    def getLineCount(self, file_name):
        self.file_name = file_name
        try:
            fopen = open(file_name, 'r')
        except:
            print('File cannot be read:', file_name)
            exit()
        count = 0
        for line in fopen:
            count += 1

        print("Line Count:{}".format(count))

    def getWordCount(self, file_name):
        self.file_name = file_name
        import re
        freq = {}  # To store the word and its corresponding word count
        file_obj = open(file_name, 'r')
        word_content = file_obj.read().lower()  # Turn all the words in our document into lowercase.

        reg_exp = re.findall(r'\b[a-z]{3,15}\b', word_content)

        for word in reg_exp:
            count = freq.get(word, 0)  # Count the frequency for a word present in our document.
            freq[word] = count + 1  # Increase the count for each word occurring more than once

        freq_list = freq.keys()
        print("Word: Count")
        for word in freq_list:
            print("{}:{}".format(word, freq[word]))

    def find_word(self, file_name, word_to_search):
        self.file_name = file_name
        self.word_to_search = word_to_search.lower()
        with open(file_name) as myFile:
            for num, line in enumerate(myFile, 1):
                if word_to_search in line.lower():
                    print("Line Number:{} \nContent:{}".format(num, line))


if __name__ == '__main__':
    from tkinter import Tk
    from tkinter.filedialog import askopenfilename

    Tk().withdraw()  # we don't want a full GUI, so keep the root window from appearing
    filelocation = askopenfilename()  # open the dialog GUI
    file_stats = file_stats()
    try:
        choice = int(input(
            "Please select one of the option: \n1. Line Count\n2. Word Count\n3. Search a word in file\n4. All\n--> "))
        if choice == 1:
            file_stats.getLineCount(filelocation)
        elif choice == 2:
            file_stats.getWordCount(filelocation)
        elif choice == 3:
            word_to_search = input("\nPlease enter a word to search:")
            file_stats.find_word(filelocation, word_to_search.lower())
        elif choice == 4:
            file_stats.getLineCount(filelocation)
            file_stats.getWordCount(filelocation)
            word_to_search = input("\nPlease enter a word to search:")
            file_stats.find_word(filelocation, word_to_search.lower())
        else:
            exit()
    except:
        print("Not a valid input")
        exit()
