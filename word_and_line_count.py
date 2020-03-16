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

if __name__ == '__main__':
    file_stats = file_stats()
    file_stats.getLineCount('count.txt')
    file_stats.getWordCount('count.txt')
