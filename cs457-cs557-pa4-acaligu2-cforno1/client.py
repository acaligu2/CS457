import sys
import socket
import time


sys.path.append('/home/vchaska1/protobuf/protobuf-3.5.1/python')
import store_pb2

class Client:
    def __init__(self, replicaList):
        self.replicaList = replicaList      #Store IP/Port of all replicas
        self.coordinatorSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.cur_coordinator = None

    def send_put_msg(self, key, val, consistency):
        msg = store_pb2.Msg()
        msg.put.key = key
        msg.put.val = val
        msg.put.level = consistency

        self.coordinatorSocket.sendall(msg.SerializeToString())

        val = self.coordinatorSocket.recv(1024)

        if val:

            s = store_pb2.Msg()
            s.ParseFromString(val)
            if(s.suc.success):

                print("Write operation completed successfully")

            else:

                print("Failed to write to replicas desired")

    def send_get_req(self, key, consistency):
        msg = store_pb2.Msg()
        msg.get.key = key
        msg.get.level = consistency
        self.coordinatorSocket.sendall(msg.SerializeToString())
        val = self.coordinatorSocket.recv(1024)
        if val:
            s = store_pb2.Msg()
            s.ParseFromString(val)

            if s.WhichOneof("msg") == "string_val":
                value = s.string_val.val
                index = value.find("M") + 1
                print ("Key: " + str(key) + " => " +  value[index:])

            elif s.WhichOneof("msg") == "suc":
                self.sendInitialization(int(self.cur_coordinator) + 1)
                corIP = self.replicaList[self.cur_coordinator][0]
                cor_port = self.replicaList[self.cur_coordinator][1]
                self.coordinatorSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.coordinatorSocket.connect((corIP, cor_port))
                self.send_get_req(key, consistency)
                                            

    def sendInitialization(self, coordinator):
        self.cur_coordinator = int(coordinator)

        for replica in replicaList:

            initSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            try:

                initSocket.connect((replica))

            except:

                print("Can't connect")
                continue

            msg = store_pb2.Msg()
            msg.init.coordinator = coordinator

            initSocket.sendall(msg.SerializeToString())


        initSocket.close()

    def run(self):

        while True:

            self.coordinatorSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            coordinator = int(input("Enter replica to contact: "))

            self.sendInitialization(coordinator)

            stringVersion = str(coordinator)
            if len(stringVersion) == 2:
                coordinator = int(stringVersion[0])

            request = input("Enter request (get/put): ")

            coordinatorIP = replicaList[coordinator][0]
            coordinatorPort = replicaList[coordinator][1]

            self.coordinatorSocket.connect((coordinatorIP, coordinatorPort))

            if(request == "put"):

                key = int(input("Key: "))
                val = input("Val: ")

                cL = input("Consistency Level: ")

                consistency = -1
                if(cL == "ONE"):
                    consistency = 0
                if(cL == "QUORUM"):
                    consistency = 1

                self.send_put_msg(key, val, consistency)

            if(request == "get"):

                key = int(input("Key: "))
                cL = input("Consistency Level: ")

                consistency = -1
                if(cL == "ONE"):
                    consistency = 0
                if(cL == "QUORUM"):
                    consistency = 1

                self.send_get_req(key, consistency)

            self.coordinatorSocket.close()

def parseReplicaFile():

    replicaList = [None] * 4

    file = open("replicas.txt", "r")

    for line in file:

        splitLines = line.split(" ")

        index = int(splitLines[0])
        replicaList[index] = (splitLines[1], int(splitLines[2]))

    file.close()

    return replicaList


if __name__ == "__main__":

    replicaList = parseReplicaFile()

    client = Client(replicaList)
    client.run()

    print("Closing socket...")
    mysocket.close()
