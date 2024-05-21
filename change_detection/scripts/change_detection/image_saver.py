#!/usr/bin/env python3
import rospy
import cv2
import pdb
from sensor_msgs.msg import Image
from cv_bridge import CvBridge, CvBridgeError
from nav_msgs.msg import Odometry
import numpy as np
from threading import Lock
import tf

DEFAULT_SAVEDIR="/data2/datasets/"

def normalizeAngle(angle):
    while angle>=np.pi:
        angle-=2*np.pi
    while angle<-np.pi:
        angle+=2*np.pi
    return angle

class image_saver:
    def __init__(self):
        # Initization of the node, name_sub
        rospy.init_node('image_saver', anonymous=True)
        self.listener = tf.TransformListener()

        # Initialize the CvBridge class
        self.bridge = CvBridge()
        self.im_count=0

        self.pose_queue=[]
        self.pose_lock=Lock()
        self.pose_sub = rospy.Subscriber("/odom", Odometry, self.pose_callback)
        
        # Setup callback function
        self.image_sub = rospy.Subscriber("/camera_throttled/color/image_raw", Image, self.image_callback)

        rospy.spin()

    def pose_callback(self, odom_msg):
        print("pose received")
        self.pose_lock.acquire()
        self.pose_queue.append(odom_msg)
        if len(self.pose_queue)>20:
            self.pose_queue.pop(0)
        self.pose_lock.release()

    def get_pose(self, tStamp):
        t=tStamp.to_nsec()
        self.pose_lock.acquire()
        top=None
        bottom=None
        for count, value in enumerate(self.pose_queue):
            if value.header.stamp.to_nsec()>t:
                top=value
                if count>0:
                    bottom=self.pose_queue[count-1]
                break
        self.pose_lock.release()
        if top is None or bottom is None:
            return None
        # Linear Interpolation between timestamps
        slopeT=(t-bottom.header.stamp.to_nsec())/(top.header.stamp.to_nsec()-bottom.header.stamp.to_nsec())
        topP=np.array([top.pose.pose.position.x,top.pose.pose.position.y,top.pose.pose.position.z])
        bottomP=np.array([bottom.pose.pose.position.x,bottom.pose.pose.position.y,bottom.pose.pose.position.z])
        pose = bottomP + slopeT*(topP-bottomP)

        # Also need to calculate orientation - interpolation between euler angles
        topQ=[top.pose.pose.orientation.x, top.pose.pose.orientation.y, top.pose.pose.orientation.z, top.pose.pose.orientation.w]
        bottomQ=[bottom.pose.pose.orientation.x, bottom.pose.pose.orientation.y, bottom.pose.pose.orientation.z, top.pose.pose.orientation.w]
        [a1,b1,topYaw]=tf.transformations.euler_from_quaternion(topQ)
        [a2,b2,bottomYaw]=tf.transformations.euler_from_quaternion(bottomQ)
        # We are going to assume that the shortest delta is the direction of rotation
        deltaY=normalizeAngle(topYaw-bottomYaw)
        if deltaY>np.pi:
            deltaY=2*np.pi-deltaY
        if deltaY<-np.pi:
            deltaY=2*np.pi + deltaY
        orientation=bottomYaw+deltaY*slopeT
        poseM=tf.transformations.rotation_matrix(orientation,(0,0,1))
        poseM[:3,3]=pose
        return poseM

    def image_callback(self, img_msg):
        try:
            #(trans,rot) = self.listener.lookupTransform('/map',img_msg.header.frame_id,img_msg.header.stamp)
            #(trans,rot) = self.listener.lookupTransform('/map','/base_link',img_msg.header.stamp)
            (trans,rot) = self.listener.lookupTransform('/base_link',img_msg.header.frame_id,img_msg.header.stamp)
            base_relativeM=np.matmul(tf.transformations.translation_matrix(trans),tf.transformations.quaternion_matrix(rot))
        except (tf.LookupException, tf.ConnectivityException, tf.ExtrapolationException):
            print("No Transform found")
            return
        print("Transform found")
        print(trans)
        odom=self.get_pose(img_msg.header.stamp)
        if odom is None:
            print("Missing odometry information - skipping")
        # Convert the ROS Image message to a CV2 Image
        poseM=np.matmul(odom,base_relativeM)
        poseQ=tf.transformations.quaternion_from_matrix(poseM)

        try:
            cv_image = self.bridge.imgmsg_to_cv2(img_msg, "bgr8")
        except CvBridgeError as e:
            rospy.logerr("CvBridge Error: {0}".format(e))    
            return

        image_fName=DEFAULT_SAVEDIR+"rgb_%05d.jpg"%(self.im_count)
        self.im_count+=1
        cv2.imwrite(image_fName,cv_image)
        text_fName=DEFAULT_SAVEDIR+"images.txt"
        with open(text_fName,"a+") as fout:
            print("%d, %f, %f, %f, %f, %0.4f, %0.4f, %0.4f, 0, %s\n"%(self.im_count,poseQ[3],poseQ[0],poseQ[1],poseQ[2],poseM[0,3],poseM[1,3],poseM[2,3],image_fName),file=fout)
            
if __name__ == '__main__':
    IT=image_saver()
 
