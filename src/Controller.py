#!/usr/bin/env python3
import rospy
import sys
from time import sleep, time
import json
from Robot import Robot
from States import WaitingAtReception
from std_msgs.msg import String
from sdp.srv import getState
from rooms import *

#####AAAAAA Issues:

#Class designed to receive messages from the world and therefore trigger the correct responses
class controller:

    robots = list() #Array containing all the robots
    booths = list()
    transitArea = None
    reception = None
    dropOff = None
    exitArea = None
    idleTimeout = 180 #The length in seconds representing how long a robot can be idle before it raises concern
    idleCheckInterval = 60 #How often the robots are checked for being idle

    #Init, takes an optional list of robot ids and an optional number of booths
    def __init__(self, robot_ids = ["0001"], numBooths = 1):
        #Rospy Init
        rospy.init_node("controller")
        self.RtoS_sub = rospy.Subscriber("RtoS", String, callback=self.callback, queue_size=20) #Creates the sub and pub objects
        self.StoR_sub = rospy.Subscriber("StoR", String, callback=self.callback1, queue_size=20)
        self.CtoS_sub = rospy.Subscriber("CtoS", String, callback=self.callback2, queue_size=20)
        self.StoR_pub = rospy.Publisher("StoR", String, queue_size=20)
        self.StoC_pub = rospy.Publisher("StoC", String, queue_size=20)
        self.getStateService = rospy.Service("getState", getState, self.getStateHandler)
        #Processing
        self.reception = Reception("1", self.transitArea)
        for robotID in robot_ids:
            self.robots.append(Robot(robotID, WaitingAtReception(), self)) #Creates the robots and adds the to the list
            self.reception.reserve(self.robots[-1], True) #Places the reservation for the robot being initially in the reception
        self.transitArea = TransitArea("1") #Creates the other rooms
        self.dropOff = DropOff("1", self.transitArea)
        self.exitArea = ExitArea("1", self.transitArea)
        for i in range(1,int(numBooths) + 1):
            self.booths.append(Booth(i, self.transitArea)) #Generates all the booths

    #Receives any RtoS messages and passes them to the respective robot
    def callback(self, data):
        parts = data.data.split(",")
        print("[MESSAGE] Message has arrived from robot: \'" + parts[0] + "\' message reads: " + parts[1])
        for robot in self.robots:
            if robot.robot_id == parts[0]:
                robot.handleMessage(parts[1])
                return
        print("Robot : \'" + parts[0] + "\' not found in controller")

    #Receives outgoing StoR messages and theses are sent also to the robot in question to update its internal state also for verbose logging
    def callback1(self,data):
        parts = data.data.split(",")
        print("[MESSAGE] Message sent to robot: \'" + parts[0] + "\' message reads: " + parts[1])
        for robot in self.robots:
            if robot.robot_id == parts[0]:
                robot.handleMessage(parts[1])
                return
        print("Robot : \'" + parts[0] + "\' not found in controller")

    #Handles CtoS messages that come from the console
    def callback2(self,data):
        parts = data.data.split(",")
        print("[MESSAGE[ Message has arrived from Console, message reads robot: " + parts[0] + " - " + parts[1])
        for robot in self.robots:
            if Robot.robot_id == parts[0]:
                robot.handleMessage(parts[1])
                return
        print("Robot : \'" + parts[0] + "\' not found in controller")

    #The handler for a Timer, checks for idle bots
    def idleCheck(self, event):
        for robot in self.robots:
            if (robot._state.toString() != "WaitingAtReception") and (robot._state.toString() != "Charging"): #If its not in a state where idle is expected
                if ((time() - robot.timeOfLastMessage) > self.idleTimeout): #Checks if its been idle too long
                    self.StoC_pub.publish(str(robot.robot_id) + ",idle") #Publishes message

    #Handler for the getState service, gets the state of a robot
    def getStateHandler(self, request):
        for robot in self.robots:
            if robot.robot_id == request.robotId:
                return robot._state.toString()
        return None

    #Connected to a Timer and publishes JSON representing the internal state of the Controller
    def getJSON(self, event):
        robotDicts = list()
        for robot in self.robots:
            robotDicts.append(robot.toDict())
        boothDicts = list()
        for booth in self.booths:
            boothDicts.append(booth.toDict())
        dictionary = {"Robots":robotDicts, "Booths":boothDicts, "Transit Area":self.transitArea.toDict(),
            "Exit Area":self.exitArea.toDict(), "Drop Off":self.dropOff.toDict(), "Reception":self.reception.toDict()}
        jsonString = json.dumps(dictionary)
        self.StoC_pub.publish("generalUpdate:" + jsonString)
        f = open("out.json", 'w')
        f.write(jsonString)
        f.close()

    """Requests rooms for a given robot, checks against available capcity. If there is no capacity for the robot
    then the method will sleep for 5 seconds and then try again. Once a room has been reserved a ROS messages is
    published to command the robot to move to its location

    :param robot: A Robot Object
    :param roomType: A String listing the room type
    :param hasHuman: A boolean that determines if the robot has a human following it
    :returns None
    """
    def requestRoom(self, robot, roomType, hasHuman):
        if roomType == "Booth":
            for booth in self.booths: #First it checks each booth
                if booth.hasReservation(robot, hasHuman): #To see if there is already a reservation
                    print("[RESERVATION] Booth: " + booth.id + " re-reserved by " + robot.robot_id)
                    self.StoR_pub.publish(String(str(robot.robot_id) + ",moveTo[location]")) #If there is then the command is sent
                    return
            #If there is no reservation
            while True: #Kept in loop
                for booth in self.booths:
                    if booth.hasCapcity(robot, hasHuman): #If a booth has capcity
                        booth.reserve(robot, hasHuman) #Its reserved
                        print("[RESERVATION] Booth: " + str(booth.id) + " reserved by " + str(robot.robot_id))
                        self.requestRoom(robot, "TransitArea", hasHuman) #Then the transit area is also reserved
                        self.StoR_pub.publish(String(str(robot.robot_id) + ",moveTo[location]")) #Command sent
                        return
                sleep(5) #If there is capcity in no booth then the method sleeps for 5 seconds and tries again
        elif roomType == "TransitArea":
            if self.transitArea.hasReservation(robot, hasHuman):
                print("[RESERVATION] Transit Area re-reserved by " + robot.robot_id)
                return
            else:
                while True:
                    if self.transitArea.hasCapcity(robot, hasHuman):
                        self.transitArea.reserve(robot, hasHuman)
                        print("[RESERVATION] Transit Area reserved by " + robot.robot_id)
                        return
                    sleep(5)
        elif roomType == "ExitArea":
            if self.exitArea.hasReservation(robot, hasHuman):
                print("[RESERVATION] Exit Area re-reserved by " + robot.robot_id)
                self.StoR_pub.publish(String(str(robot.robot_id) + ",moveTo[location]"))
                return
            else:
                while True:
                    if self.exitArea.hasCapcity(robot, hasHuman):
                        self.exitArea.reserve(robot, hasHuman)
                        print("[RESERVATION] Exit Area reserved by " + robot.robot_id)
                        self.requestRoom(robot, "TransitArea", hasHuman)
                        self.StoR_pub.publish(String(str(robot.robot_id) + ",moveTo[location]"))
                        return
                    sleep(5)
        elif roomType == "DropOff":    
            if self.dropOff.hasReservation(robot, hasHuman):
                print("[RESERVATION] DropOff Area re-reserved by " + robot.robot_id)
                self.StoR_pub.publish(String(str(robot.robot_id) + ",moveTo[location]"))
                return
            else:
                while True:
                    if self.dropOff.hasCapcity(robot, hasHuman):
                        self.dropOff.reserve(robot, hasHuman)
                        print("[RESERVATION] DropOff Area reserved by " + robot.robot_id)
                        self.requestRoom(robot, "TransitArea", hasHuman)
                        self.StoR_pub.publish(String(str(robot.robot_id) + ",moveTo[location]"))
                        return
                    sleep(5)
        elif roomType == "Reception":    
            if self.reception.hasReservation(robot, hasHuman):
                print("[RESERVATION] Reception Area re-reserved by " + robot.robot_id)
                self.StoR_pub.publish(String(str(robot.robot_id) + ",moveTo[location]"))
                return
            else:
                while True:
                    if self.reception.hasCapcity(robot, hasHuman):
                        self.reception.reserve(robot, hasHuman)
                        print("[RESERVATION] Reception Area reserved by " + robot.robot_id)
                        self.requestRoom(robot, "TransitArea", hasHuman)
                        self.StoR_pub.publish(String(str(robot.robot_id) + ",moveTo[location]"))
                        return
                    sleep(5)
        else:
            print("Error in reservation code at controller level")

    """Method clears all reservations for a given robot. Typically run when a robot arrives at
    a destination.

    :param robot: A Robot Object
    """
    def releaseReservations(self, robot, room):
        if room == "Booth":
            for booth in self.booths:
                booth.clearReservation(robot)
        elif room == "Reception":
            self.reception.clearReservation(robot)
        elif room == "TransitArea":
            self.transitArea.clearReservation(robot)
        elif room == "ExitArea":
            self.exitArea.clearReservation(robot)
        elif room == "DropOff":
            self.dropOff.clearReservation(robot)
        else:
            print("Error in releaseing reservations")
        print("[RESERVATION] Robot: " + robot.robot_id + " has released its reservation for " + room)



def main(args):
    robots = args[1].split(",")
    control = controller(robots,args[2])
    rospy.Timer(rospy.Duration(control.idleCheckInterval), control.idleCheck)
    rospy.Timer(rospy.Duration(5), control.getJSON)
    try:
        rospy.spin()
    except KeyboardInterrupt:
        print("Shutting Down")

if __name__ == "__main__":
    main(sys.argv)