#Anthony Caligure - CS 457: PA1

import socket
import sys
import threading
from wsgiref.handlers import format_date_time
from datetime import datetime
import time
from time import mktime
from pathlib import Path
import os
import mimetypes
import os.path

#Dictionary of file accesses
accessCounts = {}

#Lock for adding a new file to the accessCount dictionary
addLock = threading.Lock()

#Lock for incrementing a file's access count
incrementLock = threading.Lock()

#Lock the dictionary and add an entry for a newly requested file
def addToAccessCounts(fileName):

    addLock.acquire()
    accessCounts[fileName] = 1
    addLock.release()

#Lock the dictionary and increment the counter for the accessed file
def incrementAccessCount(fileName):

    incrementLock.acquire()
    try:
        accessCounts[fileName] += 1
    except:
        print("Error with dictionary")
        exit(1)
    finally:
        incrementLock.release()

#Prints info to stdout of the Server Terminal
def printToServerShell(desiredFile, clientIP, clientPort):

    print(desiredFile + "|" + clientIP + "|" + str(clientPort) + "|" + str(accessCounts[desiredFile]))

#Creates message to be sent back to client
def createResponse(statusCode, fileName):

    print("sending response")

    #Declare variable for HTTP Response
    statusString = ""

    #Response Message for invalid file
    if statusCode == "404 Not Found":

        statusString += "HTTP/1.1 404 Not Found"
        statusString += '\n'
        statusString += "The specified file couldn't be found"
        statusString += '\n'

        #Convert to byte data
        statusString = statusString.encode()

    #Actual HTTP Response Message
    else:

        #Size of requested file
        fileSize = os.path.getsize(fileName)

        #Get last modified date of file
        lastModified = datetime.fromtimestamp(os.path.getmtime(fileName))
        lStamp = mktime(lastModified.timetuple())

        #Get file MIME Type
        fileMime = mimetypes.MimeTypes().guess_type(fileName)[0]

        #Request Info
        statusString += ("HTTP/1.1 200 OK")
        statusString += '\n'

        #Timestamp
        now = datetime.now()
        tStamp = mktime(now.timetuple())
        statusString += "Date: "
        statusString += format_date_time(tStamp)
        statusString += '\n'

        #Server Info:
        statusString += "Server: Acaligu2/V1.0\n"

        #Last Modified Date
        statusString += "Last-Modified: " + format_date_time(lStamp) + '\n'

        #Content-Type (MIME)
        statusString += "Accept-Ranges: bytes\n"

        #Content Length
        statusString += "Content-Length: " + str(fileSize) + '\n'

        #Content Type:
        statusString += "Content-Type: " + str(fileMime) + "\n"

        statusString += '\n'

        #Convert message to byte data
        statusString = statusString.encode()

        #Open file and read bytes
        fileData = open(fileName, "rb")

        #Append byte data from file to the repsonse message
        statusString += fileData.read(fileSize)

        #close file
        fileData.close()

    #Return statusString (byte data) to be sent to client
    return statusString

#Retrieve data for request
def httpHandler(connectedSocket, newClient):

    #Variable for contents of file
    fileData = ""

    #Save working directory "cs457-cs557-pa1-acaligu2"
    owd = os.getcwd()

    responseMessage = ""

    #Recieve byte data of request from wget client
    data = connectedSocket.recv(1024)

    #Decode data into a string
    formattedRequest = data.decode()

    #Seperate request by line
    requestLines = []
    requestLines = formattedRequest.splitlines()

    #Grab first line of the request and parse the desired fileName
    desiredFile = requestLines[0].split(' ')[1][1:]

    #Grab client IP and Port info to print to terminal
    clientIP, clientPort = newClient

    #Locating the file in www directory
    try:

        #cd into WWW directory to find files
        os.chdir("www")

    #WWW directory doesn't exist
    except:
        print("Error: Couldn't find directory")
        print("Exiting...")
        exit(1)

    #Resource has been found and is a file
    if(os.path.isfile(desiredFile)):

        #Already been accessed; increment counter
        if desiredFile in accessCounts:
            incrementAccessCount(desiredFile)

        #New file, add to dictionary
        else:
            addToAccessCounts(desiredFile)

        #Create a response message
        responseMessage = createResponse("200 OK", desiredFile)

        #Print client info and access count to terminal
        printToServerShell(desiredFile, clientIP, clientPort)

    #File not found: 404
    else:
        responseMessage = createResponse("404 Not Found", "")

    #Change back to original working directory
    os.chdir(owd)

    #Send repsonse message to wget client
    bytesSent = connectedSocket.send(responseMessage)

    return;

#Create TCP Socket and Listen for incoming connections
def initializeServer():

    #Initialize
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    #Bind socket
    sock.bind(('', 0))

    #Retrieve hostname and port
    hostName = socket.getfqdn()
    portNum = sock.getsockname()[1]
    print('\n')
    print("Starting Server on " + hostName + " with port " + str(portNum))
    print('\n')

    #Listen for incoming connections
    sock.listen(10)

    while True:
        #Accept the connection, create a new thread to process HTTP GET request
        connectedSocket, newClient = sock.accept()
        newClientThread = threading.Thread(target = httpHandler, args = (connectedSocket, newClient))
        newClientThread.start()

def main():

    initializeServer()

if __name__ == "__main__":
    main()
