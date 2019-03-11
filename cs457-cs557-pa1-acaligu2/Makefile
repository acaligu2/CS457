c.o:
	gcc -g -c $?

# compile client and server
all: httpServer

# compile client only
#confclient: confclient.o confutils.o
#	gcc -g -o confclient confclient.o  confutils.o

# compile server program
httpServer: httpServer.o
		g++ -g -o httpServer httpServer.o

clean:
	rm -f *.o httpServer
