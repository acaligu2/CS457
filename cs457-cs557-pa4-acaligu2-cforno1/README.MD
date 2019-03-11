Anthony Caligure, Cris Forno

Tools:
	Google Protobuf
	Python 3.5


How to Run:
	To run the client the commands are: python3 client.py
	To run a replica: python3 replica.py [0-3] <consistency mechanism>

Tasks:
	Both:
		Made a client program
	Anthony:
		Set up sockets between replicas
		Handled write requests
		implemented Paritioner function
		implemented hinted handoff
	Cris:
		handled read requests
		handled read repair
		Handled how timestamps are implemented

Completion:
	Everthing works, but we have to restart all the replicas when
	a replica wants to reconnect in certain cases.



