import sys
sys.path.append('/home/vchaska1/protobuf/protobuf-3.5.1/python')
import socket
from pathlib import Path
import store_pb2 as store
import struct
import time
import threading
import _thread as thread

'''

    TODO:

        ***Ensure quorum is complete for gets**

        1.) Restructure to utilize threads
        2.) Handle disconnects and keep track of active replicas
        3.) Test "get" consistency levels
        4.) Read-repair
        5.) Hinted-handoff
        6.) when recieved get request that we dont own, it doesnt work

'''



class Replica:

    def __init__(self, replica_num, server_socket, mech, rM):
        self.storeLock = threading.Lock()
        self.logName = "writeAhead" + replica_num + ".txt"
        self.coordinator = -1                   #Determines whether to wait or send
        self.clientSocket = server_socket
        self.replica_num = replica_num
        self.hostName = ""
        self.portNum = 0
        self.keyValStore = {}                   #key => val:time_stamp
        self.replicaList = [None] * 4           #Store IP/Port of all other replicas
        self.neighborSockets = [None] * 4
        self.const_mech = mech                  # 0 => read repair -- 1 => hinted handoff
        self.OKs = []
        self.successfulPuts = 0
        self.hints = [[], [], [], []]           #2d Array of hints
        self.recoveryMode = rM
        self.handling_read_repair = False
        self.RR_lock = threading.Lock()         #read repair lock so no two threads can set the boolean to true
        self.recoveryFlag = False

    def parseReplicaFile(self):

        file = open("replicas.txt", "r")

        for line in file:

            splitLines = line.split(" ")

            if splitLines[0] == self.replica_num:

                self.hostName = splitLines[1]
                self.portNum = int(splitLines[2])

                index = int(self.replica_num)
                self.replicaList[index] = (self.hostName, self.portNum)

            else:

                index = int(splitLines[0])
                self.replicaList[index] = (splitLines[1], int(splitLines[2]))

        file.close()

    #Determines the first replica in the cluster
    def bytePartitioner(self, key):

        firstRep = -1

        if key in range(64):
            firstRep = 0
        elif key in range(64, 128):
            firstRep = 1
        elif key in range(128, 192):
            firstRep = 2
        elif key in range(192, 256):
            firstRep = 3
        else:
            print("Key not in range")
            sys.exit(1)

        return firstRep

    def read_repair(self, key):
        begins = self.bytePartitioner(key)
        timestamps = {} # replica num => timestamp
        msg = store.Msg()
        msg.timestamp.key = key
        for i in range(3):
            contact = (int(begins) + i) % 4
            if int(contact) == int(self.replica_num):
                continue

            socket = self.neighborSockets[contact]
            # we want to find out who has the latest version of the object
            socket.sendall(msg.SerializeToString())
            response = socket.recv(1024)
            parser = store.Msg()
            if response:
                parser.ParseFromString(response)
                if parser.WhichOneof("msg") == "pair_read":
                    timestamps[contact] = parser.pair_read.val

        #now that we have all the timestamps of all the replicas we have to compare the
        # timestamps
        timestamps[int(self.replica_num)] = self.keyValStore[key] # add our own verison
        max_timestamp = 0
        max_val = ""
        for replica_num, val in timestamps.items():
            value, timestamp = val.split(":")
            timestamp = float(timestamp)
            if max_timestamp < timestamp:
                max_timestamp = timestamp
                max_val = value

        

        self.keyValStore[key] = max_val + ":" + str(time.time())


        read_repair_msg = store.Msg()
        read_repair_msg.pair_write.key = key
        read_repair_msg.pair_write.val = max_val

        for i in range(3):
            contact = (int(begins) + i) % 4
            if int(contact) == int(self.replica_num):
                continue
            socket = self.neighborSockets[contact]
            socket.sendall(read_repair_msg.SerializeToString())

    def get_consistency_helper(self, key, socket, contact):
        msg = store.Msg()
        msg.pair_read.key = key
        msg.pair_read.val = self.keyValStore[key].split(":")[0]

        socket.sendall(msg.SerializeToString())

        response = socket.recv(1024)

        

        msg = store.Msg()
        if response:
            msg.ParseFromString(response)
            if msg.WhichOneof("msg") == "suc":
                if msg.suc.success == True:
                    self.OKs.append(True)
                else:
                    if self.const_mech == 0:
                        # do a read repair
                        self.RR_lock.acquire()
                        if self.handling_read_repair == False:
                            self.handling_read_repair = True
                            self.RR_lock.release()
                            self.read_repair(key)
                        else:
                            self.RR_lock.release()

        thread.exit()
    def reset_msg(self, socket, contact):
        msg = store.Msg()
        msg.pair_write.key = -1
        msg.pair_write.val = ":)"
        socket.sendall(msg.SerializeToString())
        thread.exit()

    def get_consistency(self, key, level):
        OK_len = 0
        if level == 0:
            OK_len = 1
        elif level == 1:
            OK_len = 2

        self.OKs = []
        begins = self.bytePartitioner(key)

        for i in range(4):
            contact = (int(begins) + i) % 4
            if int(contact) == int(self.replica_num):
                continue
            sock = self.neighborSockets[contact]
            if i == 3:
                thread.start_new_thread(self.reset_msg, (sock, contact))
            else:
                thread.start_new_thread(self.get_consistency_helper, (int(key), sock, contact))

        counter = 0 # use this as a time out mechanism
        time.sleep(3)
        while len(self.OKs) < OK_len and counter < 5: # we only need one OK from the replicas
            time.sleep(0.5)
            counter += 1

        if len(self.OKs) < OK_len:
            return False
        else:
            return True


    def get(self, key, level, client_socket):

        consistency_worked = None

        if key in self.keyValStore:
            val_to_send = self.keyValStore[key].split(":")
            val_to_send = val_to_send[0]
            time_stamp = val_to_send[1]

            consistency_worked = self.get_consistency(key, level)
            msg_to_send = store.Msg()
            msg_to_send.string_val.val = val_to_send
            client_socket.sendall(msg_to_send.SerializeToString())

        else:
            #we contact the next replica in the ring
            msg_to_send = store.Msg()
            msg_to_send.suc.success = False

            client_socket.sendall(msg_to_send.SerializeToString())

            for i in range(4):
                if i == int(self.replica_num):
                    continue
                sock = self.neighborSockets[i]
                self.reset_msg(sock, 0)

            consistency_worked = True
            '''
            sock_to_contact = self.neighborSockets[(int(self.replica_num) + 1) % 4]
            msg_to_send = store.Msg()
            msg_to_send.get.key = key
            msg_to_send.get.level = level
            print("key is not in this node, asking next node...")
            sock_to_contact.sendall(msg_to_send.SerializeToString())
            val = sock_to_contact.recv(1024)
            if val:
                msg_to_respond = store.Msg()
                msg_to_respond.ParseFromString(val)
                if msg_to_respond.WhichOneof("msg") == "string_val":
                    msg = store.Msg()
                    msg.string_val.val = msg_to_respond.string_val.val
                    client_socket.sendall(msg.SerializeToString())
                    consistency_worked = True
            '''
        if consistency_worked == True:
            return
        else:
            # send a message to the client that it didn't work
            not_OK = store.Msg()
            not_OK.suc.success = False
            client_socket.sendall(not_OK.SerializeToString())

    #Put a value into the key/val store
    def put(self, key, val, level, client_socket):

        #Determine how many replicas are needed before returning to client
        replicasForConsistency = level + 1

        #First replica determined by the byte partitioner
        firstReplica = self.bytePartitioner(key)

        #Second and third are clockwise in the cluster
        secondReplica = (firstReplica + 1) % 4
        thirdReplica = (firstReplica + 2) % 4

        operationReplicas = [firstReplica, secondReplica, thirdReplica]

        print("I will be storing this data on")
        print(str(firstReplica) + " " + str(secondReplica) + " " + str(thirdReplica))

        #Amount of replicas that have successfully completed the request
        successfulPuts = 0

        #Loop through all four replcias
        for i in range(4):

            #Send to only those replicas desired by coordinator
            if(i in operationReplicas):

                #Create message to send to replicas
                msg = store.Msg()
                msg.pair_write.key = key
                msg.pair_write.val = val

                index = operationReplicas.index(i)

                #This replica is required to store the info
                if(operationReplicas[index] == int(self.replica_num)):

                    #Write to log before adding to local memory

                    self.storeLock.acquire()

                    writeLogInfo = open(self.logName, "a")
                    writeLogInfo.write(str(key) + ":" + val + ":" + str(time.time()) +"\n")
                    writeLogInfo.close()

                    self.keyValStore[key] = val;

                    self.storeLock.release()

                    #"Put" was successful, return to client if consistency level is met
                    if key in self.keyValStore:

                        print("Added: " + val + " to location: " + str(key))
                        successfulPuts += 1

                        #We have reached QUORUM or ONE consistency
                        if(successfulPuts == replicasForConsistency):

                                msg_to_send = store.Msg()
                                msg_to_send.suc.success = True
                                client_socket.sendall(msg_to_send.SerializeToString())

                    continue

                #Find socket connecting to other replica
                repSock = self.neighborSockets[operationReplicas[index]]
                time.sleep(0.5)

                #Send message containing key and val to replica
                try:

                    repSock.sendall(msg.SerializeToString())

                except socket.error:

                    self.neighborSockets[i].close()
                    print("Failed to connect to " + str(i))

                    if(self.const_mech == 1):
                        print("Storing <" + str(key) + val + "> as a hint")

                        self.hints[i].append((key, val))

                        print(self.hints)

                    continue


                #Sleep to see effect of consistency level
                time.sleep(2)

                #Receive response
                try:

                    msg = repSock.recv(1024)

                except socket.error:

                    self.neighborSockets[i].close()
                    print("Failed to connect to " + str(i))
                    if(self.const_mech == 1):
                        print("Storing <" + str(key) + val + "> as a hint")

                        self.hints[i].append((key, val))

                        print(self.hints)

                    continue

                store_msg = store.Msg()
                store_msg.ParseFromString(msg)
                msgType = store_msg.WhichOneof("msg")
                valid = self.parse_msg(repSock, ("", ""), store_msg)

                #The put in a replica was successful
                if(valid):

                    print("Successful copy to " + str(operationReplicas[index]))

                    successfulPuts += 1

                    #We have enough for the consistency, send success to client
                    if(successfulPuts == replicasForConsistency):

                            msg_to_send = store.Msg()
                            msg_to_send.suc.success = True
                            client_socket.sendall(msg_to_send.SerializeToString())

                    continue

                else:

                    print("Failed copy to " + str(operationReplicas[index]))

                    #Append hint to list for replica that failed
                    self.neighborSockets[i].close()
                    print("Failed to connect to " + str(i))
                    if(self.const_mech == 1):
                        print("Storing <" + str(key) + val + "> as a hint")

                        self.hints[i].append((key, val))

                        print(self.hints)

                    continue

            #Message to get unused replcias out of the wait function
            else:

                if(i == int(self.replica_num)):
                    continue

                msg = store.Msg()
                msg.pair_write.key = -1
                msg.pair_write.val = "None"
                repSock = self.neighborSockets[i]
                time.sleep(0.5)
                repSock.sendall(msg.SerializeToString())

        #Send failure to client
        if(successfulPuts < replicasForConsistency):

            print("Didn't get to consistency level")

            msg_to_send = store.Msg()
            msg_to_send.suc.success = False
            client_socket.sendall(msg_to_send.SerializeToString())

    def compare_pair(self, key, val, sock):

        msg = store.Msg()

        print(self.keyValStore)

        if key in self.keyValStore:

            if self.keyValStore[key].split(":")[0] == val:
                msg.suc.success = True
            else:
                msg.suc.success = False
        else:
            msg.suc.success = False

        sock.sendall(msg.SerializeToString())

        timestamp = sock.recv(1024)

        parser = store.Msg()
        parser.ParseFromString(timestamp)
        if parser.WhichOneof("msg") == "timestamp":
            self.retrieve_timestamp(key, sock)

    #Parse write-ahead log at beginning of execution
    def parseWriteLog(self):

        writeLogInfo = open(self.logName, "r")

        emptyCheck = writeLogInfo.read(1).strip()
        writeLogInfo.close()

        if not emptyCheck:
            writeLogInfo.close()
            return

        writeLogInfo = open(self.logName, "r")
        for line in writeLogInfo:

            components = line.strip().split(":")
            key = int(components[0])
            val = components[1] + ":" + components[2]
            self.keyValStore[key] = val

        writeLogInfo.close()

    #Adds hints to coordinators keyValStore
    def appendHints(self, hKeys, hVals):

        for i in range(len(hKeys)):

            writeLogInfo = open(self.logName, "a")
            writeLogInfo.write(str(hKeys[i]) + ":" + hVals[i] + ":" + str(time.time()) +"\n")
            writeLogInfo.close()

            self.keyValStore[hKeys[i]] = hVals[i]

            print("Added <" + str(hKeys[i]) + " " + hVals[i] + ">")


    def retrieve_timestamp(self, key, socket):
        msg = store.Msg()
        msg.pair_read.key = key
        msg.pair_read.val = self.keyValStore[int(key)]
        socket.sendall(msg.SerializeToString())

        write_this = socket.recv(1024)
        #call pair_write

        if write_this:
            s = store.Msg()
            s.ParseFromString(write_this)
            if s.WhichOneof("msg") == "pair_write":
                self.pair_write(s.pair_write.key, s.pair_write.val)


    def pair_write(self, key, val):
        
        self.storeLock.acquire()
        
        writeLogInfo = open(self.logName, "a")
        writeLogInfo.write(str(key) + ":" + val + ":" + str(time.time()) + "\n")
        writeLogInfo.close()
        
        self.keyValStore[key] = val;
        
        self.storeLock.release()

        if key in self.keyValStore:
            
            print("Added: " + val + " to location: " + str(key))
            return "True"

        else:

            return "False"


    #Function to parse all protobuf messages
    def parse_msg(self, client_socket, client_add, msg):

        if not msg:

            print ("Error: null message")
            return "False"

        msg_type = msg.WhichOneof("msg")

        if msg_type == "put":

            self.put(msg.put.key, msg.put.val, msg.put.level, client_socket)

        elif msg_type == "get":

             self.get(msg.get.key, msg.get.level, client_socket)

        #Used to communicate between replicas
        elif msg_type == "pair_write":

            key = msg.pair_write.key
            val = msg.pair_write.val

            if(key == -1):

                return "False"
            return self.pair_write(key, val)

        #Used to determine if an operation was successful or not
        elif msg_type == "suc":

            outcome = msg.suc.success
            if outcome:
                return "True"
            else:
                return "False"

        #Initializes the coordinator for a request
        elif msg_type == "init":

            newCoord = -1
            string = str(msg.init.coordinator)

            if len(string) == 2:
                self.recoveryFlag = True
                print("This is a recovery")
                newCoord = int(string[0])

            else:
                newCoord = msg.init.coordinator

            self.coordinator = newCoord

        elif msg_type == "pair_read":

            print("We got a pair_read function")
            self.compare_pair(msg.pair_read.key, msg.pair_read.val, client_socket)

        elif msg_type == "hint":

                hKeys = []
                hVals = []

                hKeys.extend(msg.hint.hintKey)
                hVals.extend(msg.hint.hintValue)

                if(hKeys[0] == -1):

                    return False

                self.appendHints(hKeys, hVals)

                return True

        elif msg_type == "timestamp":
            self.retrieve_timestamp(msg.timestamp.key, client_socket)
        else:

            return False

    def performHintedHandoff(self):

        msg = store.Msg()

        time.sleep(int(self.replica_num))

        if(len(self.hints[self.coordinator]) > 0):

            print("I have hints for the coordinator")

            k = []
            v = []
            for i in range(len(self.hints[self.coordinator])):

                k.append(self.hints[self.coordinator][i][0])
                v.append(self.hints[self.coordinator][i][1])

            msg.hint.hintKey.extend(k)
            msg.hint.hintValue.extend(v)

            print(self.hints[self.coordinator])
            self.hints[self.coordinator].clear()
            print(self.hints)

        else:

            print("No hints for the coordinator")
            noHint = []
            noHint.append(-1)
            noVal = []
            noVal.append("-")
            msg.hint.hintKey.extend(noHint)
            msg.hint.hintValue.extend(noVal)

        self.neighborSockets[self.coordinator].sendall(msg.SerializeToString())

    #Wait for coordinator to assign a task
    def waitForInstruction(self):

        print("Waiting for coordinator <" + str(self.coordinator) + "> to assign a request")

        if(self.recoveryFlag):
            t = threading.Thread(target = self.attemptToConnect)
            t.start()
            t.join()

        #Hinted Handoff Consistency Mechanism
        if(self.const_mech == 1):

            self.performHintedHandoff()

        try:

            coordinatorSocket = self.neighborSockets[self.coordinator]

            time.sleep(2)

            msg = coordinatorSocket.recv(1024)

            store_msg = store.Msg()
            store_msg.ParseFromString(msg)
            msgType = store_msg.WhichOneof("msg")
            valid = self.parse_msg(coordinatorSocket, ("", ""), store_msg)

            if(valid == "False"):

                return

            elif(valid == "True"):

                msg = store.Msg()
                msg.suc.success = True
                coordinatorSocket.sendall(msg.SerializeToString())

        except (KeyboardInterrupt, OSError) as e:

            if self.clientSocket:

                self.clientSocket.close()
                self.clientSocket = None

            for sock in self.neighborSockets:

                if sock:
                    sock.close()
                    sock = None

            sys.exit()

    def receiveHintedHandoff(self, socket):

        print("")
        print("---------------Handling Hints---------------")
        print("")

        time.sleep(2)

        hintMessagesReceived = 0

        for socket in self.neighborSockets:

            if(self.neighborSockets.index(socket) == self.coordinator):
                continue
            else:
                msg = socket.recv(1024)
                if msg:

                    store_msg = store.Msg()
                    store_msg.ParseFromString(msg)
                    msgType = store_msg.WhichOneof("msg")

                    ret = self.parse_msg(socket, ("", ""), store_msg)
                    if(ret == "True"):
                        print("Got a hint from " + str(self.neighborSockets.index(socket)))

                    elif(ret == "False"):
                        print("No hint from " + str(self.neighborSockets.index(socket)))

        print(self.keyValStore)

        print("")
        print("-------------Done Handling Hints-------------")
        print("")

    def coordinatorFunction(self, client_sock, client_add, store_msg):

        if self.recoveryMode:

            for replica in reversed(self.replicaList):

                index = self.replicaList.index(replica)

                if(index == int(self.replica_num)):

                    continue

                else:

                    incomingConn, incomingAddr = self.clientSocket.accept()

                    '''

                        for every replica in replicaList

                            ip = replica[0].getIp()

                            if incomingAddr[0] == ip

                                self.neighborSockets[replicaList.index(replica)] = incomingConn

                    '''

                    self.neighborSockets[self.replicaList.index(replica)] = incomingConn
                    print("Got connection from " + str(index) + ": {" + incomingAddr[0] + ", " + str(incomingAddr[1]) + "}")
                    print("")

        #Wait to receive hints if consistency mechanism is hinted handoff
        if(self.const_mech == 1):

            self.receiveHintedHandoff(client_sock)

        infoMsg = client_sock.recv(1024)

        if infoMsg:

            store_msg = store.Msg()
            store_msg.ParseFromString(infoMsg)

        self.parse_msg(client_sock, client_add, store_msg)

    #Wait for replica to connect
    def listenForReplica(self, replica):

        index = self.replicaList.index(replica)
        print("Listening for connection from " + str(index) + "...")

        incomingConn, incomingAddr = self.clientSocket.accept()

        #Store info for later communication
        self.neighborSockets[index] = incomingConn

        print("Got connection from " + str(index) + ": {" + incomingAddr[0] + ", " + str(incomingAddr[1]) + "}")
        print("")

    #Try to connect to given replica
    def connectToReplica(self, replica):

        while True:

            try:

                newSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                newSocket.connect((replica))

            except socket.error:

                continue

            break

        #Store socket info in list for later communication
        index = self.replicaList.index(replica)
        print(str(index))
        self.neighborSockets[index] = newSocket

        print("Connected to " + str(index) + ": {" + newSocket.getsockname()[0] + ", " + str(newSocket.getsockname()[1]) + "}")
        print("")

    #Create connections among all replicas
    def initializeNeighboringSockets(self):

        waitForConnection = []
        connectTo = []

        for i in range(4):

            if i == int(self.replica_num):

                waitForConnection = self.replicaList[:i]
                connectTo = self.replicaList[i + 1:]
                break

        for replica in waitForConnection:
            self.listenForReplica(replica)

        for replica in reversed(connectTo):
            self.connectToReplica(replica)

    def attemptToConnect(self):

        seconds = (int(self.replica_num) + 3) % 4
        time.sleep(seconds)

        while True:

            try:

                newSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                newSocket.connect(self.replicaList[self.coordinator])
                print("Connected")
                break

            except socket.error:
                continue

        self.neighborSockets[self.coordinator] = newSocket

    def run(self):

        self.clientSocket.bind(('', self.portNum))

        print("Starting Replica " + self.replica_num + ": {" + self.hostName + ":" + str(self.portNum) + "}")

        self.neighborSockets[int(self.replica_num)] = self.clientSocket

        self.clientSocket.listen(30)

        print("---------------Connecting All Replicas---------------")
        print("")

        if not self.recoveryMode:

            self.initializeNeighboringSockets()

        print("--------------Ready To Receive Requests--------------")

        #Check for write-log file
        writeLog = Path("./" + self.logName)
        if(writeLog.exists()):
            self.parseWriteLog()

        while True:

            client_sock = None
            client_add = None

            try:

                while(self.coordinator == -1):

                    try:

                        client_sock, client_add = self.clientSocket.accept()

                        msg = client_sock.recv(1024)

                        if msg:

                            store_msg = store.Msg()
                            store_msg.ParseFromString(msg)
                            msgType = store_msg.WhichOneof("msg")
                            self.parse_msg(client_sock, client_add, store_msg)

                    except KeyboardInterrupt or AttributeError:

                        if self.clientSocket:
                            self.clientSocket.close()

                        for sock in self.neighborSockets:

                            if sock:

                                sock.close()

                        break


                #Replica
                if(self.replica_num != str(self.coordinator)):

                    self.waitForInstruction()

                #coordinator
                else:

                    print("Connected to client as coordinator: {" + client_add[0] + ":" + str(client_add[1]) + "}")

                    self.coordinatorFunction(client_sock, client_add, store_msg)

            except KeyboardInterrupt:

                for sock in self.neighborSockets:

                    if sock:
                        sock.close()

                if self.clientSocket:
                    self.clientSocket.close()

                break

            self.coordinator = -1;
            client_sock.close()

def main(args):

    if len(args) != 3 and len(args) != 4:
        print("python3 replpica.py <replica number> <consistency mechanism>")
        sys.exit(1)

    replicaNumber = args[1]
    mech = args[2]
    if(mech == "repair"):
        mech = 0
    elif (mech == "hinted"):
        mech = 1

    rM = False
    if(len(args) == 4):
        if(args[3] == 1):
            rM = True

    clientSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    replica_server = Replica(replicaNumber, clientSocket, mech, rM)
    replica_server.parseReplicaFile()
    replica_server.run()


if __name__ == "__main__":
    main(sys.argv)
