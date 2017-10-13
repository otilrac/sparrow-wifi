#!/usr/bin/python3
# 
# Copyright 2017 ghostop14
# 
# This is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.
# 
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this software; see the file COPYING.  If not, write to
# the Free Software Foundation, Inc., 51 Franklin Street,
# Boston, MA 02110-1301, USA.
# 

import sys
import csv
import os
import subprocess
import re
import json
import datetime
from dateutil import parser
import requests
from time import sleep
from threading import Thread

from PyQt5.QtWidgets import QApplication, QMainWindow,  QDesktopWidget
from PyQt5.QtWidgets import QMessageBox, QFileDialog, QInputDialog, QLineEdit
from PyQt5.QtWidgets import QAction, QComboBox, QLabel, QPushButton, QCheckBox, QTableWidget,QTableWidgetItem, QHeaderView, QMenu
#from PyQt5.QtWidgets import QTabWidget, QWidget, QVBoxLayout
from PyQt5.QtChart import QChart, QChartView, QLineSeries, QValueAxis
from PyQt5.QtGui import QPen, QFont, QBrush, QColor, QPainter
# Qt for global colors.  See http://doc.qt.io/qt-5/qt.html#GlobalColor-enum
from PyQt5.QtCore import Qt, QRect, QTimer
from PyQt5.QtGui import QIcon, QRegion
from PyQt5 import QtCore

# from PyQt5.QtCore import QCoreApplication # programatic quit
from wirelessengine import WirelessEngine, WirelessNetwork
from sparrowgps import GPSEngine, GPSStatus
from telemetry import TelemetryDialog
from sparrowtablewidgets import IntTableWidgetItem, DateTableWidgetItem
from sparrowmap import MapMarker, MapEngine
from sparrowdialogs import MapSettingsDialog, TelemetryMapSettingsDialog

# ------------------  Global functions ------------------------------
def stringtobool(instr):
    if (instr == 'True' or instr == 'true'):
        return True
    else:
        return False

# ------------------  Global functions for agent HTTP requests ------------------------------
def makeGetRequest(url):
    try:
        response = requests.get(url)
    except:
        return -1, ""
        
    if response.status_code != 200:
        return response.status_code, ""
        
    htmlResponse=response.text
    return response.status_code, htmlResponse

def requestRemoteGPS(remoteIP, remotePort):
    url = "http://" + remoteIP + ":" + str(remotePort) + "/gps/status"
    statusCode, responsestr = makeGetRequest(url)
    
    if statusCode == 200:
        try:
            gpsjson = json.loads(responsestr)
            gpsStatus = GPSStatus()
            
            gpsStatus.gpsInstalled = stringtobool(gpsjson['gpsinstalled'])
            gpsStatus.gpsRunning = stringtobool(gpsjson['gpsrunning'])
            gpsStatus.gpsSynchronized = stringtobool(gpsjson['gpssynch'])
            
            if gpsStatus.gpsSynchronized:
                # These won't be there if it's not synchronized
                gpsStatus.latitude = float(gpsjson['latitude'])
                gpsStatus.longitude = float(gpsjson['longitude'])
                gpsStatus.altitude = float(gpsjson['altitude'])
                gpsStatus.speed = float(gpsjson['speed'])
                
            return 0, "", gpsStatus
        except:
            return -2, "Error parsing remote agent response", None
    else:
        return -1, "Error connecting to remote agent", None


def requestRemoteNetworks(remoteIP, remotePort, remoteInterface, channelList=None):
    url = "http://" + remoteIP + ":" + str(remotePort) + "/wireless/networks/" + remoteInterface
    
    if (channelList is not None) and (len(channelList) > 0):
        url += "?frequencies="
        for curChannel in channelList:
            url += str(curChannel) + ','
            
    if url.endswith(','):
        url = url[:-1]
        
    statusCode, responsestr = makeGetRequest(url)
    
    if statusCode == 200:
        try:
            networkjson = json.loads(responsestr)
            wirelessNetworks = {}
            
            for curNetDict in networkjson['networks']:
                newNet = WirelessNetwork.createFromJsonDict(curNetDict)
                wirelessNetworks[newNet.getKey()] = newNet
                
            return networkjson['errCode'], networkjson['errString'], wirelessNetworks
        except:
            return -2, "Error parsing remote agent response", None
    else:
        return -1, "Error connecting to remote agent", None


# ------------------  Local network scan thread  ------------------------------
class ScanThread(Thread):
    def __init__(self, interface, mainWin, channelList=None):
        super(ScanThread, self).__init__()
        self.interface = interface
        self.mainWin = mainWin
        self.signalStop = False
        self.scanDelay = 0.5  # seconds
        self.threadRunning = False
        self.channelList = channelList
        
    def run(self):
        self.threadRunning = True
        
        while (not self.signalStop):
            # Scan all / normal mode
            if (self.channelList is None) or (len(self.channelList) == 0):
                retCode, errString, wirelessNetworks = WirelessEngine.scanForNetworks(self.interface)
                if (retCode == 0):
                    # self.statusBar().showMessage('Scan complete.  Found ' + str(len(wirelessNetworks)) + ' networks')
                    if len(wirelessNetworks) > 0:
                        self.mainWin.scanresults.emit(wirelessNetworks)
                else:
                        if (retCode != WirelessNetwork.ERR_DEVICEBUSY):
                            self.mainWin.errmsg.emit(retCode, errString)
            
                if (retCode == WirelessNetwork.ERR_DEVICEBUSY):
                    # Shorter sleep for faster results
                    # sleep(0.2)
                    # Switched back for now.  Might be running too fast.
                    sleep(self.scanDelay)
                else:
                    sleep(self.scanDelay)
            else:
                # Channel hunt mode
                for curFrequency in self.channelList:
                    retCode, errString, wirelessNetworks = WirelessEngine.scanForNetworks(self.interface, curFrequency)
                    if (retCode == 0):
                        # self.statusBar().showMessage('Scan complete.  Found ' + str(len(wirelessNetworks)) + ' networks')
                        if len(wirelessNetworks) > 0:
                            self.mainWin.scanresults.emit(wirelessNetworks)
                    else:
                            if (retCode != WirelessNetwork.ERR_DEVICEBUSY):
                                self.mainWin.errmsg.emit(retCode, errString)
                
                    if (retCode == WirelessNetwork.ERR_DEVICEBUSY):
                        # Shorter sleep for faster results
                        # sleep(0.2)
                        # Switched back for now.  Might be running too fast.
                        sleep(self.scanDelay)
                    else:
                        sleep(self.scanDelay)
                    
        self.threadRunning = False

# ------------------  Remote agent network scan thread  ------------------------------
class RemoteScanThread(Thread):
    def __init__(self, interface, mainWin, channelList=None):
        super(RemoteScanThread, self).__init__()
        self.interface = interface
        self.mainWin = mainWin
        self.signalStop = False
        self.scanDelay = 0.5  # seconds
        self.threadRunning = False
        self.remoteAgentIP = "127.0.0.1"
        self.remoteAgentPort = 8020
        self.channelList = channelList
        
    def run(self):
        self.threadRunning = True
        
        while (not self.signalStop):
            retCode, errString, wirelessNetworks = requestRemoteNetworks(self.remoteAgentIP, self.remoteAgentPort, self.interface, self.channelList)
            if (retCode == 0):
                # self.statusBar().showMessage('Scan complete.  Found ' + str(len(wirelessNetworks)) + ' networks')
                if len(wirelessNetworks) > 0:
                    self.mainWin.scanresults.emit(wirelessNetworks)
            else:
                    if (retCode != WirelessNetwork.ERR_DEVICEBUSY):
                        self.mainWin.errmsg.emit(retCode, errString)
            
            if (retCode == WirelessNetwork.ERR_DEVICEBUSY):
                # Shorter sleep for faster results
                sleep(0.2)
            else:
                sleep(self.scanDelay)
            
        self.threadRunning = False

# ------------------  GPSEngine override onGPSResult to notify the main window when the GPS goes synchnronized  ------------------------------
class GPSEngineNotifyWin(GPSEngine):
    def __init__(self, mainWin):
        super().__init__()
        self.mainWin = mainWin
        self.isSynchronized = False

    def onGPSResult(self, gpsResult):
        super().onGPSResult(gpsResult)

        if self.isSynchronized != gpsResult.isValid:
            # Allow GPS to sync / de-sync and notify
            self.isSynchronized = gpsResult.isValid
            self.mainWin.gpsSynchronizedsignal.emit()

# ------------------  Global color list that we'll cycle through  ------------------------------
colors = [Qt.black, Qt.red, Qt.darkRed, Qt.green, Qt.darkGreen, Qt.blue, Qt.darkBlue, Qt.cyan, Qt.darkCyan, Qt.magenta, Qt.darkMagenta, Qt.darkGray]

# ------------------  Main Application Window  ------------------------------
class mainWindow(QMainWindow):
    
    # Notify signals
    resized = QtCore.pyqtSignal()
    scanresults = QtCore.pyqtSignal(dict)
    errmsg = QtCore.pyqtSignal(int, str)
    gpsSynchronizedsignal = QtCore.pyqtSignal()
    
    # For help with qt5 GUI's this is a great tutorial:
    # http://zetcode.com/gui/pyqt5/
    
    def __init__(self):
        super().__init__()

        self.telemetryWindows = {}
        
        self.scanMode="Normal"
        self.huntChannelList = []
        
        # GPS engine
        self.gpsEngine = GPSEngineNotifyWin(self)
        self.gpsSynchronized = False
        self.gpsSynchronizedsignal.connect(self.onGPSSyncChanged)
        
        # Local network scan
        self.scanRunning = False
        self.scanIsBlocking = False
        
        self.nextColor = 0
        self.lastSeries = None

        self.scanThread = None
        self.scanDelay = 0.5
        self.scanresults.connect(self.scanResults)
        self.errmsg.connect(self.onErrMsg)
        
        self.remoteAgentIP = ''
        self.remoteAgentPort = 8020
        self.remoteAutoUpdates = True
        self.remoteScanRunning = False
        self.remoteScanIsBlocking = False
        self.remoteScanThread = None
        self.remoteScanDelay = 0.5
        self.lastRemoteState = False
        
        desktopSize = QApplication.desktop().screenGeometry()
        #self.mainWidth=1024
        #self.mainHeight=768
        self.mainWidth = desktopSize.width() * 3 / 4
        self.mainHeight = desktopSize.height() * 3 / 4
        
        self.initUI()
        
        if os.geteuid() != 0:
            self.runningAsRoot = False
            self.statusBar().showMessage('You need to have root privileges to run local scans.  Please exit and rerun it as root')
            print("You need to have root privileges to run this script.\nPlease try again, this time using 'sudo'. Exiting.")
            QMessageBox.question(self, 'Warning',"You need to have root privileges to run local scans.", QMessageBox.Ok)

            #self.close()
        else:
            self.runningAsRoot = True
    
    def initUI(self):
        # self.setGeometry(10, 10, 800, 600)
        self.resize(self.mainWidth, self.mainHeight)
        self.center()
        self.setWindowTitle('Sparrow-WiFi Analyzer')
        self.setWindowIcon(QIcon('wifi_icon.png'))        

        self.createMenu()
        
        self.createControls()
        
        self.setMinimumWidth(800)
        self.setMinimumHeight(400)
        
        self.show()
        
        # Set up GPS check timer
        self.gpsTimer = QTimer()
        self.gpsTimer.timeout.connect(self.onGPSTimer)
        self.gpsTimer.setSingleShot(True)
        
        self.gpsTimerTimeout = 10000
        self.gpsTimer.start(self.gpsTimerTimeout)   # Check every 10 seconds

    def resizeEvent(self, event):
        # self.resized.emit()
        # self.statusBar().showMessage('Window resized.')
        # return super(mainWin, self).resizeEvent(event)
        size = self.geometry()
        self.networkTable.setGeometry(10, 103, size.width()-20, size.height()/2-105)
        # self.tabs.setGeometry(30, self.height()/2+20, self.width()-60, self.height()/2-55)
        self.Plot24.setGeometry(10, size.height()/2+10, size.width()/2-10, size.height()/2-40)
        self.Plot5.setGeometry(size.width()/2+5, size.height()/2+10,size.width()/2-15, size.height()/2-40)
        self.lblGPS.move(size.width()-90, 30)
        self.btnGPSStatus.move(size.width()-50, 34)
        
        if size.width() < 850:
            self.setGeometry(size.x(), size.y(), 850, size.height())

            
    def createControls(self):
        # self.statusBar().setStyleSheet("QStatusBar{background:rgba(204,229,255,255);color:black;border: 1px solid blue; border-radius: 1px;}")
        self.statusBar().setStyleSheet("QStatusBar{background:rgba(192,192,192,255);color:black;border: 1px solid blue; border-radius: 1px;}")
        if GPSEngine.GPSDRunning():
            self.gpsEngine.start()
            self.statusBar().showMessage('Local gpsd Found.  System Ready.')
        else:
            self.statusBar().showMessage('Note: No local gpsd running.  System Ready.')


        # Interface droplist
        self.lblInterface = QLabel("Local Interface", self)
        self.lblInterface.setGeometry(5, 30, 120, 30)
        
        self.combo = QComboBox(self)
        self.combo.move(130, 30)

        interfaces=WirelessEngine.getInterfaces()
        
        if (len(interfaces) > 0):
            for curInterface in interfaces:
                self.combo.addItem(curInterface)
        else:
            self.statusBar().showMessage('No wireless interfaces found.')

        self. combo.activated[str].connect(self.onInterface)        
        
        # Scan Button
        self.btnScan = QPushButton("&Scan", self)
        self.btnScan.setCheckable(True)
        self.btnScan.setShortcut('Ctrl+S')
        self.btnScan.setStyleSheet("background-color: rgba(0,128,192,255); border: none;")
        self.btnScan.move(260, 30)
        self.btnScan.clicked[bool].connect(self.onScanClicked)
        
        # Scan Mode
        self.lblScanMode = QLabel("Scan Mode:", self)
        self.lblScanMode.setGeometry(380, 30, 120, 30)
        
        self.scanModeCombo = QComboBox(self)
        self.scanModeCombo.setStatusTip('All-channel normal scans can take 5-10 seconds per sweep.  Use Hunt mode for faster response time on a selected channel.')
        self.scanModeCombo.move(455, 30)
        self.scanModeCombo.addItem("Normal")
        self.scanModeCombo.addItem("Hunt")
        self.scanModeCombo.currentIndexChanged.connect(self.onScanModeChanged)
        
        self.lblScanMode = QLabel("Hunt Channel or Frequencies(s):", self)
        self.lblScanMode.setGeometry(565, 30, 200, 30)
        self.huntChannels = QLineEdit(self)
        self.huntChannels.setStatusTip('Channels or center frequencies can be specified.  List should be comma-separated.')
        self.huntChannels.setGeometry(763, 30, 100, 30)
        self.huntChannels.setText('1')

        # Hide them to start
        self.huntChannels.setVisible(False)
        self.lblScanMode.setVisible(False)
        
        # Age out checkbox
        self.cbAgeOut = QCheckBox(self)
        self.cbAgeOut.move(10, 70)
        self.lblAgeOut = QLabel("Remove networks not seen in the past 3 minutes", self)
        self.lblAgeOut.setGeometry(30, 70, 300, 30)
        
        # Network Table
        self.networkTable = QTableWidget(self)
        self.networkTable.setColumnCount(11)
        # self.networkTable.setGeometry(10, 100, self.mainWidth-60, self.mainHeight/2-105)
        self.networkTable.setShowGrid(True)
        self.networkTable.setHorizontalHeaderLabels(['macAddr', 'SSID', 'Security', 'Privacy', 'Channel', 'Frequency', 'Signal Strength', 'Bandwidth', 'Last Seen', 'First Seen', 'GPS'])
        self.networkTable.resizeColumnsToContents()
        self.networkTable.setRowCount(0)
        self.networkTable.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

        self.networkTable.horizontalHeader().sectionClicked.connect(self.onTableHeadingClicked)
        self.networkTable.cellClicked.connect(self.onTableClicked)
        
        # Network Table right-click menu
        self.ntRightClickMenu = QMenu(self)
        newAct = QAction('Telemetry', self)        
        newAct.setStatusTip('View network telemetry data')
        newAct.triggered.connect(self.onShowTelemetry)
        self.ntRightClickMenu.addAction(newAct)
        
        # Attached it to the table
        self.networkTable.setContextMenuPolicy(Qt.CustomContextMenu)
        self.networkTable.customContextMenuRequested.connect(self.showNTContextMenu)
        
        self.createCharts()
        
        # GPS Indicator
        self.lblGPS = QLabel("GPS:", self)
        self.lblGPS.move(850, 30)
        
        rect = QRect(0,0,20,20)
        region = QRegion(rect,QRegion.Ellipse)
        self.btnGPSStatus = QPushButton("", self)
        self.btnGPSStatus.move(900, 34)
        self.btnGPSStatus.setFixedWidth(30)
        self.btnGPSStatus.setFixedHeight(30)
        self.btnGPSStatus.setMask(region)
        self.btnGPSStatus.clicked.connect(self.onGPSStatusIndicatorClicked)
        
        if GPSEngine.GPSDRunning():
            if self.gpsEngine.gpsValid():
                self.btnGPSStatus.setStyleSheet("background-color: green; border: 1px;")
            else:
                self.btnGPSStatus.setStyleSheet("background-color: yellow; border: 1px;")
        else:
            self.btnGPSStatus.setStyleSheet("background-color: red; border: 1px;")
 
    def createMenu(self):
        # Create main menu bar
        menubar = self.menuBar()
        fileMenu = menubar.addMenu('&File')
        
        # Create File Menu Items
        newAct = QAction('&New', self)        
        newAct.setShortcut('Ctrl+N')
        newAct.setStatusTip('Clear List')
        newAct.triggered.connect(self.onClearData)
        fileMenu.addAction(newAct)

        # import
        newAct = QAction('&Import from CSV', self)        
        newAct.setStatusTip('Import from saved CSV')
        newAct.triggered.connect(self.importData)
        fileMenu.addAction(newAct)
        
        # export
        newAct = QAction('&Export to CSV', self)        
        newAct.setStatusTip('Export to CSV')
        newAct.triggered.connect(self.exportData)
        fileMenu.addAction(newAct)
        
        # Agent Menu Items
        helpMenu = menubar.addMenu('&Agent')
        self.menuRemoteAgent = QAction('Remote Agent', self)        
        self.menuRemoteAgent.setStatusTip('Remote Agent')
        self.menuRemoteAgent.setCheckable(True)
        self.menuRemoteAgent.changed.connect(self.onRemoteAgent)
        helpMenu.addAction(self.menuRemoteAgent)
        
        # GPS Menu Items
        gpsMenu = menubar.addMenu('&Geo')
        newAct = QAction('Create Access Point Map', self)        
        newAct.setStatusTip('Plot access point coordinates from the table on a Google map')
        newAct.triggered.connect(self.onGoogleMap)
        gpsMenu.addAction(newAct)
        
        newAct = QAction('Create SSID Map', self)        
        newAct.setStatusTip('Plot coordinates for a single SSID saved from telemetry window on a Google map')
        newAct.triggered.connect(self.onGoogleMapTelemetry)
        gpsMenu.addAction(newAct)
        
        gpsMenu.addSeparator()
        
        newAct = QAction('GPS Status', self)        
        newAct.setStatusTip('Show GPS Status')
        newAct.triggered.connect(self.onGPSStatus)
        gpsMenu.addAction(newAct)
        
        if (os.path.isfile('/usr/bin/xgps') or os.path.isfile('/usr/local/bin/xgps')):
            newAct = QAction('Launch XGPS - Local', self)        
            newAct.setStatusTip('Show GPS GUI against local gpsd')
            newAct.triggered.connect(self.onXGPSLocal)
            gpsMenu.addAction(newAct)
        
            newAct = QAction('Launch XGPS - Remote', self)        
            newAct.setStatusTip('Show GPS GUI against remote gpsd')
            newAct.triggered.connect(self.onXGPSRemote)
            gpsMenu.addAction(newAct)
            
        # View Menu Items
        ViewMenu = menubar.addMenu('&View')
        newAct = QAction('Telemetry For Selected Network', self)        
        newAct.setStatusTip('Show telemetry screen for selected network')
        newAct.triggered.connect(self.onShowTelemetry)
        ViewMenu.addAction(newAct)
        
        # Help Menu Items
        helpMenu = menubar.addMenu('&Help')
        newAct = QAction('About', self)        
        newAct.setStatusTip('About')
        newAct.triggered.connect(self.onAbout)
        helpMenu.addAction(newAct)
        #newMenu = QMenu('New', self)
        #actNewSqlite = QAction('New SQLite', self) 
        #actNewPostgres = QAction('New Postgres', self) 
        #newMenu.addAction(actNewSqlite)
        #newMenu.addAction(actNewpostgres)
        # fileMenu.addMenu(newMenu)
        
        # exitAct = QAction(QIcon('exit.png'), '&Exit', self)        
        exitAct = QAction('&Exit', self)        
        exitAct.setShortcut('Ctrl+X')
        exitAct.setStatusTip('Exit application')
        exitAct.triggered.connect(self.close)
        fileMenu.addAction(exitAct)

    def createCharts(self):
        self.chart24 = QChart()
        titleFont = QFont()
        titleFont.setPixelSize(18)
        titleBrush = QBrush(QColor(0, 0, 255))
        self.chart24.setTitleFont(titleFont)
        self.chart24.setTitleBrush(titleBrush)
        self.chart24.setTitle('2.4 GHz')
        self.chart24.legend().hide()
        
        # Axis examples: https://doc.qt.io/qt-5/qtcharts-multiaxis-example.html
        newAxis = QValueAxis()
        newAxis.setMin(0)
        newAxis.setMax(15)
        newAxis.setTickCount(16)
        newAxis.setLabelFormat("%d")
        newAxis.setTitleText("Channel")
        self.chart24.addAxis(newAxis, Qt.AlignBottom)
        
        newAxis = QValueAxis()
        newAxis.setMin(-100)
        newAxis.setMax(-20)
        newAxis.setTickCount(9)
        newAxis.setLabelFormat("%d")
        newAxis.setTitleText("dBm")
        self.chart24.addAxis(newAxis, Qt.AlignLeft)
        
        chartBorder = Qt.darkGray
        self.Plot24 = QChartView(self.chart24, self)
        self.Plot24.setBackgroundBrush(chartBorder)
        self.Plot24.setRenderHint(QPainter.Antialiasing)

        self.chart5 = QChart()
        self.chart5.setTitleFont(titleFont)
        self.chart5.setTitleBrush(titleBrush)
        self.chart5.setTitle('5 GHz')
        self.chart5.createDefaultAxes()
        self.chart5.legend().hide()
        
        newAxis = QValueAxis()
        newAxis.setMin(30)
        newAxis.setMax(170)
        newAxis.setTickCount(14)
        newAxis.setLabelFormat("%d")
        newAxis.setTitleText("Channel")
        self.chart5.addAxis(newAxis, Qt.AlignBottom)
        
        newAxis = QValueAxis()
        newAxis.setMin(-100)
        newAxis.setMax(-20)
        newAxis.setTickCount(9)
        newAxis.setLabelFormat("%d")
        newAxis.setTitleText("dBm")
        self.chart5.addAxis(newAxis, Qt.AlignLeft)
        
        self.Plot5 = QChartView(self.chart5, self)
        self.Plot5.setBackgroundBrush(chartBorder)
        self.Plot5.setRenderHint(QPainter.Antialiasing)
    
    def onScanModeChanged(self):
        self.scanMode = str(self.scanModeCombo.currentText())
        
        if self.scanMode == "Normal":
            self.huntChannels.setVisible(False)
            self.lblScanMode.setVisible(False)
        else:
            self.huntChannels.setVisible(True)
            self.lblScanMode.setVisible(True)
            
        self.getHuntChannels()
        
    def getHuntChannels(self):
        channelStr = self.huntChannels.text()
        channelStr = channelStr.replace(' ', '')
        
        if (',' in channelStr):
            tmpList = channelStr.split(',')
        else:
            tmpList = []
            if (len(channelStr)>0):
                try:
                    # quick check that we really have a number
                    intVal = int(channelStr)
                    tmpList.append(channelStr)
                except:
                    pass
        
        for curItem in tmpList:
            if len(curItem) > 0:
                try:
                    freqForChannel = WirelessEngine.getFrequencyForChannel(curItem)
                    
                    if freqForChannel is not None:
                        self.huntChannelList.append(int(freqForChannel))
                    else:
                        self.huntChannelList.append(int(curItem))
                except:
                    QMessageBox.question(self, 'Error',"Could not figure channel out from " + curItem, QMessageBox.Ok)
        
    def onXGPSLocal(self):
        subprocess.Popen('xgps')
        
    def onXGPSRemote(self):
        text, okPressed = QInputDialog.getText(self, "Remote Agent","Please provide gpsd IP:", QLineEdit.Normal, "127.0.0.1:2947")
        if okPressed and text != '':
            # Validate the input
            p = re.compile('^([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}:[0-9]{1,5})')
            specIsGood = True
            try:
                agentSpec = p.search(text).group(1)
                remoteIP = agentSpec.split(':')[0]
                remotePort = int(agentSpec.split(':')[1])
                
                if remotePort < 1 or remotePort > 65535:
                    QMessageBox.question(self, 'Error',"Port must be in an acceptable IP range (1-65535)", QMessageBox.Ok)
                    specIsGood = False
            except:
                QMessageBox.question(self, 'Error',"Please enter it in the format <IP>:<port>", QMessageBox.Ok)
                specIsGood = False
                
            if not specIsGood:
                self.menuRemoteAgent.setChecked(False)
                return
                    
            args = ['xgps', remoteIP + ":" + str(remotePort)]
            subprocess.Popen(args)
        
    def onShowTelemetry(self):
        curRow = self.networkTable.currentRow()
        
        if curRow == -1:
            return
        
        curNet = self.networkTable.item(curRow, 1).data(Qt.UserRole+1)
        
        if curNet == None:
            return
       
        if curNet.getKey() not in self.telemetryWindows:
            telemetryWindow = TelemetryDialog()
            telemetryWindow.show()
            self.telemetryWindows[curNet.getKey()] = telemetryWindow
        else:
            telemetryWindow = self.telemetryWindows[curNet.getKey()]
        
        # Can also key off of self.telemetryWindow.isVisible()
        telemetryWindow.show()
        telemetryWindow.activateWindow()
        
        # User could have selected a different network.
        telemetryWindow.updateNetworkData(curNet)            
        
    def showNTContextMenu(self, pos):
        self.ntRightClickMenu.exec_(self.networkTable.mapToGlobal(pos))
        # self.ntRightClickMenu.exec_(pos)
 
    def onGPSTimer(self):
        self.onGPSStatus()
        self.gpsTimer.start(self.gpsTimerTimeout)
        
    def onGoogleMap(self):
        rowPosition = self.networkTable.rowCount()

        if rowPosition <= 0:
            return
            
        mapSettings, ok = MapSettingsDialog.getSettings()

        if not ok:
            return
            
        if len(mapSettings.outputfile) == 0:
            QMessageBox.question(self, 'Error',"Please provide an output file.", QMessageBox.Ok)
            return
            
        markers = []
        
        # Range goes to last # - 1
        for curRow in range(0, rowPosition):
            try:
                curData = self.networkTable.item(curRow, 1).data(Qt.UserRole+1)
            except:
                curData = None
            
            if (curData):
                newMarker = MapMarker()
                
                newMarker.label = WirelessEngine.convertUnknownToString(curData.ssid)
                newMarker.label = newMarker.label[:mapSettings.maxLabelLength]
                
                if mapSettings.plotstrongest:
                    newMarker.latitude = curData.strongestgps.latitude
                    newMarker.longitude = curData.strongestgps.longitude
                    newMarker.barCount = WirelessEngine.getSignalQualityFromDB0To5(curData.strongestsignal)
                else:
                    newMarker.latitude = curData.gps.latitude
                    newMarker.longitude = curData.gps.longitude
                    newMarker.barCount = WirelessEngine.getSignalQualityFromDB0To5(curData.signal)
                    
                markers.append(newMarker)
                    
        if len(markers) > 0:
            retVal = MapEngine.createMap(mapSettings.outputfile,mapSettings.title,markers, connectMarkers=False, openWhenDone=True, mapType=mapSettings.mapType)
            
            if not retVal:
                QMessageBox.question(self, 'Error',"Unable to generate map to " + mapSettings.outputfile, QMessageBox.Ok)

    def onGoogleMapTelemetry(self):
        mapSettings, ok = TelemetryMapSettingsDialog.getSettings()

        if not ok:
            return
            
        if len(mapSettings.inputfile) == 0:
            QMessageBox.question(self, 'Error',"Please provide an input file.", QMessageBox.Ok)
            return
            
        if len(mapSettings.outputfile) == 0:
            QMessageBox.question(self, 'Error',"Please provide an output file.", QMessageBox.Ok)
            return
            
        markers = []
        
        with open(mapSettings.inputfile, 'r') as f:
            reader = csv.reader(f)
            raw_list = list(reader)
            
            # remove blank lines
            while [] in raw_list:
                raw_list.remove([])
                
            if len(raw_list) > 1:
                # Check header row looks okay
                if str(raw_list[0]) != "['macAddr', 'SSID', 'Strength', 'Timestamp', 'GPS', 'Latitude', 'Longitude', 'Altitude']":
                    QMessageBox.question(self, 'Error',"File format doesn't look like exported telemetry data saved from the telemetry window.", QMessageBox.Ok)
                    return
                        
                # Ignore header row
                # Range goes to last # - 1
                for i in range (1, len(raw_list)):
                    
                    # Plot first, last, and every Nth point
                    if ((i % mapSettings.plotNthPoint == 0) or (i == 1) or (i == (len(raw_list)-1))) and (len(raw_list[i]) > 0):
                        newMarker = MapMarker()
                        
                        if (i == 1) or (i == (len(raw_list)-1)):
                            # Only put first and last marker labels on.  No need to pollute the map if there's a lot of points
                            newMarker.label = WirelessEngine.convertUnknownToString(raw_list[i][1])
                            newMarker.label = newMarker.label[:mapSettings.maxLabelLength]
                        
                        newMarker.latitude = float(raw_list[i][5])
                        newMarker.longitude = float(raw_list[i][6])
                        newMarker.barCount = WirelessEngine.getSignalQualityFromDB0To5(int(raw_list[i][2]))
                            
                        markers.append(newMarker)
                    
        if len(markers) > 0:
            retVal = MapEngine.createMap(mapSettings.outputfile,mapSettings.title,markers, connectMarkers=True, openWhenDone=True, mapType=mapSettings.mapType)
            
            if not retVal:
                QMessageBox.question(self, 'Error',"Unable to generate map to " + mapSettings.outputfile, QMessageBox.Ok)
        
    def onGPSStatus(self):
        if (not self.menuRemoteAgent.isChecked()):
            # Checking local GPS
            if GPSEngine.GPSDRunning():
                if self.gpsEngine.gpsValid():
                    self.gpsSynchronized = True
                    self.btnGPSStatus.setStyleSheet("background-color: green; border: 1px;")
                    self.statusBar().showMessage('Local gpsd service is running and satellites are synchronized.')
                else:
                    self.gpsSynchronized = False
                    self.btnGPSStatus.setStyleSheet("background-color: yellow; border: 1px;")
                    self.statusBar().showMessage("Local gpsd service is running but it's not synchronized with the satellites yet.")
                    
            else:
                self.gpsSynchronized = False
                self.statusBar().showMessage('No local gpsd running.')
                self.btnGPSStatus.setStyleSheet("background-color: red; border: 1px;")
        else:
            # Checking remote
            errCode, errMsg, gpsStatus = requestRemoteGPS(self.remoteAgentIP, self.remoteAgentPort)
            
            if errCode == 0:
                if (gpsStatus.gpsSynchronized):
                    self.gpsSynchronized = True
                    self.btnGPSStatus.setStyleSheet("background-color: green; border: 1px;")
                    self.statusBar().showMessage("Remote GPS is running and synchronized.")
                elif (gpsStatus.gpsRunning):
                    self.gpsSynchronized = False
                    self.btnGPSStatus.setStyleSheet("background-color: yellow; border: 1px;")
                    self.statusBar().showMessage("Remote GPS is running but it has not synchronized with the satellites yet.")
                else:
                    self.gpsSynchronized = False
                    self.statusBar().showMessage("Remote GPS service is not running.")
                    self.btnGPSStatus.setStyleSheet("background-color: red; border: 1px;")
            else:
                self.statusBar().showMessage("Remote GPS Error: " + errMsg)
                self.btnGPSStatus.setStyleSheet("background-color: red; border: 1px;")
            
    def onGPSSyncChanged(self):
        # GPS status has changed
        self.onGPSStatus()

    def onTableHeadingClicked(self, logical_index):
        header = self.networkTable.horizontalHeader()
        order = Qt.DescendingOrder
        # order = Qt.DescendingOrder
        if not header.isSortIndicatorShown():
            header.setSortIndicatorShown( True )
        elif header.sortIndicatorSection()==logical_index:
            # apparently, the sort order on the header is already switched
            # when the section was clicked, so there is no need to reverse it
            order = header.sortIndicatorOrder()
        header.setSortIndicator( logical_index, order )
        self.networkTable.sortItems(logical_index, order )

        
    def onTableClicked(self, row, col):
        if (self.lastSeries is not None):
            # Change the old one back
            if (self.lastSeries):
                pen = self.lastSeries.pen()
                pen.setWidth(2)
                self.lastSeries.setPen(pen)
                self.lastSeries.setVisible(False)
                self.lastSeries.setVisible(True)
            
        selectedSeries = self.networkTable.item(row, 1).data(Qt.UserRole)
        
        if (selectedSeries):
            pen = selectedSeries.pen()
            pen.setWidth(6)
            selectedSeries.setPen(pen)
            selectedSeries.setVisible(False)
            selectedSeries.setVisible(True)
            
            self.lastSeries = selectedSeries
        else:
            selectedSeries = None

    def onRemoteScanClicked(self, pressed):
        
        if not self.remoteAutoUpdates:
            # Single-shot mode.
            if (self.combo.count() > 0):
                curInterface = str(self.combo.currentText())
                self.statusBar().showMessage('Scanning on interface ' + curInterface)
            else:
                self.btnScan.setChecked(False)
                return
                
            
            self.scanModeCombo.setEnabled(False)
            self.huntChannels.setEnabled(False)
            
            self.btnScan.setEnabled(False)
            self.btnScan.setStyleSheet("background-color: rgba(224,224,224,255); border: none;")
            self.btnScan.setText('&Scanning')
            self.btnScan.repaint()
            if self.scanMode == "Normal" or (len(self.huntChannelList) == 0):
                retCode, errString, wirelessNetworks = requestRemoteNetworks(self.remoteAgentIP, self.remoteAgentPort, curInterface)
            else:
                retCode, errString, wirelessNetworks = requestRemoteNetworks(self.remoteAgentIP, self.remoteAgentPort, curInterface, self.huntChannelList)
            
            self.scanModeCombo.setEnabled(True)
            self.huntChannels.setEnabled(True)
            
            self.btnScan.setEnabled(True)
            self.btnScan.setStyleSheet("background-color: rgba(2,128,192,255); border: none;")
            self.btnScan.setText('&Scan')
            if (retCode == 0):
                if len(wirelessNetworks) > 0:
                    self.scanresults.emit(wirelessNetworks)
                self.statusBar().showMessage('Ready')
            else:
                    if (retCode != WirelessNetwork.ERR_DEVICEBUSY):
                        self.errmsg.emit(retCode, errString)
                        
                        
            self.btnScan.setShortcut('Ctrl+S')
            self.btnScan.setChecked(False)
            return
            
        # Auto update
        self.remoteScanRunning = pressed
        
        if not self.remoteScanRunning:
            if self.remoteScanThread:
                self.remoteScanThread.signalStop = True
                
                while (self.remoteScanThread.threadRunning):
                    self.statusBar().showMessage('Waiting for active scan to terminate...')
                    sleep(0.2)
                    
                self.remoteScanThread = None
                    
            self.statusBar().showMessage('Ready')
        else:
            if (self.combo.count() > 0):
                curInterface = str(self.combo.currentText())
                self.statusBar().showMessage('Scanning on interface ' + curInterface)
                if self.scanMode == "Normal" or (len(self.huntChannelList) == 0):
                    self.remoteScanThread = RemoteScanThread(curInterface, self)
                else:
                    self.remoteScanThread = RemoteScanThread(curInterface, self, self.huntChannelList)
                    
                self.remoteScanThread.scanDelay = self.remoteScanDelay
                self.remoteScanThread.start()
            else:
                QMessageBox.question(self, 'Error',"No wireless adapters found.", QMessageBox.Ok)
                self.remoteScanRunning = False
                self.btnScan.setChecked(False)
                
        if self.btnScan.isChecked():
            # Scanning is on.  Turn red to indicate click would stop
            self.btnScan.setStyleSheet("background-color: rgba(255,0,0,255); border: none;")
            self.btnScan.setText('&Stop scanning')
            self.menuRemoteAgent.setEnabled(False)
        else:
            self.btnScan.setStyleSheet("background-color: rgba(2,128,192,255); border: none;")
            self.btnScan.setText('&Scan')
            self.menuRemoteAgent.setEnabled(True)

        # Need to reset the shortcut after changing the text
        self.btnScan.setShortcut('Ctrl+S')

    def onGPSStatusIndicatorClicked(self):
        if self.menuRemoteAgent.isChecked():
            self.onXGPSRemote()
        else:
            if GPSEngine.GPSDRunning():
                self.onXGPSLocal()
        
    def onScanClicked(self, pressed):
        if self.menuRemoteAgent.isChecked():
            # We're in remote mode.  Let's handle it there
            self.onRemoteScanClicked(pressed)
            return
            
        # We're in local mode.
        self.scanRunning = pressed
        
        if not self.scanRunning:
            # Want to stop a running scan (self.scanRunning represents the NEW pressed state)
            if self.scanThread:
                self.scanThread.signalStop = True
                
                while (self.scanThread.threadRunning):
                    self.statusBar().showMessage('Waiting for active scan to terminate...')
                    sleep(0.2)
                    
                self.scanThread = None
                    
            self.statusBar().showMessage('Ready')
        else:
            # Want to start a new scan
            if (not self.runningAsRoot):
                QMessageBox.question(self, 'Warning',"You need to have root privileges to run local scans.", QMessageBox.Ok)
                self.btnScan.setChecked(False)
                self.scanRunning = False
                return

            if (self.combo.count() > 0):
                curInterface = str(self.combo.currentText())
                self.statusBar().showMessage('Scanning on interface ' + curInterface)
                if self.scanMode == "Normal" or (len(self.huntChannelList) == 0):
                    self.scanThread = ScanThread(curInterface, self)
                else:
                    self.getHuntChannels()
                    self.scanThread = ScanThread(curInterface, self, self.huntChannelList)
                self.scanThread.scanDelay = self.scanDelay
                self.scanThread.start()
            else:
                QMessageBox.question(self, 'Error',"No wireless adapters found.", QMessageBox.Ok)
                self.scanRunning = False
                self.btnScan.setChecked(False)
                
        if self.btnScan.isChecked():
            # Scanning is on.  Turn red to indicate click would stop
            self.btnScan.setStyleSheet("background-color: rgba(255,0,0,255); border: none;")
            self.btnScan.setText('&Stop scanning')
            self.menuRemoteAgent.setEnabled(False)
            self.scanModeCombo.setEnabled(False)
            self.huntChannels.setEnabled(False)
        else:
            self.btnScan.setStyleSheet("background-color: rgba(2,128,192,255); border: none;")
            self.btnScan.setText('&Scan')
            self.menuRemoteAgent.setEnabled(True)
            self.scanModeCombo.setEnabled(True)
            self.huntChannels.setEnabled(True)
            
        # Need to reset the shortcut after changing the text
        self.btnScan.setShortcut('Ctrl+S')
        
    def scanResults(self, wirelessNetworks):
        if self.scanRunning:
            # Running local.  If we have a good GPS, update the networks
            # NOTE: We don't have to worry about remote scans.  They'll fill the GPS results in the data that gets passed to us.
            if (self.gpsSynchronized and (self.gpsEngine.lastCoord is not None)):
                for curKey in wirelessNetworks.keys():
                    curNet = wirelessNetworks[curKey]
                    curNet.gps = self.gpsEngine.lastCoord
                
        self.populateTable(wirelessNetworks)
        
    def onErrMsg(self, errCode, errMsg):
        self.statusBar().showMessage("Error ["+str(errCode) + "]: " + errMsg)
        
        if ((errCode == WirelessNetwork.ERR_NETDOWN) or (errCode == WirelessNetwork.ERR_OPNOTSUPPORTED) or 
            (errCode == WirelessNetwork.ERR_OPNOTPERMITTED)):
            if self.scanThread:
                self.scanThread.signalStop = True
                
                while (self.scanThread.threadRunning):
                    sleep(0.2)
                    
                self.scanThread = None
                self.scanRunning = False
                self.btnScan.setChecked(False)
                
                
    def populateTable(self, wirelessNetworks):
        rowPosition = self.networkTable.rowCount()
        
        if rowPosition > 0:
            # Range goes to last # - 1
            for curRow in range(0, rowPosition):
                try:
                    curData = self.networkTable.item(curRow, 1).data(Qt.UserRole+1)
                except:
                    curData = None
                    
                if (curData):
                    # We already have the network.  just update it
                    for curKey in wirelessNetworks.keys():
                        curNet = wirelessNetworks[curKey]
                        if curData.getKey() == curNet.getKey():
                            # Match.  Item was already in the table.  Let's update it
                            self.networkTable.item(curRow, 2).setText(curNet.security)
                            self.networkTable.item(curRow, 3).setText(curNet.privacy)
                            self.networkTable.item(curRow, 4).setText(str(curNet.getChannelString()))
                            self.networkTable.item(curRow, 5).setText(str(curNet.frequency))
                            self.networkTable.item(curRow, 6).setText(str(curNet.signal))
                            self.networkTable.item(curRow, 7).setText(str(curNet.bandwidth))
                            self.networkTable.item(curRow, 8).setText(curNet.lastSeen.strftime("%m/%d/%Y %H:%M:%S"))
                            
                            # Carry forward firstSeen
                            curNet.firstSeen = curData.firstSeen # This is one field to carry forward
                            
                            # Check strongest signal
                            if curData.signal > curNet.signal:
                                curNet.strongestsignal = curData.signal
                                curNet.strongestgps.latitude = curData.gps.latitude
                                curNet.strongestgps.longitude = curData.gps.longitude
                                curNet.strongestgps.altitude = curData.gps.altitude
                                curNet.strongestgps.speed = curData.gps.speed
                            
                            self.networkTable.item(curRow, 9).setText(curNet.firstSeen.strftime("%m/%d/%Y %H:%M:%S"))
                            if curNet.gps.isValid:
                                self.networkTable.item(curRow, 10).setText('Yes')
                            else:
                                self.networkTable.item(curRow, 10).setText('No')
                            curNet.foundInList = True
                            self.networkTable.item(curRow, 1).setData(Qt.UserRole+1, curNet)
                            
                            # Update series
                            curSeries = self.networkTable.item(curRow, 1).data(Qt.UserRole)
                            
                            # Check if we have a telemetry window
                            if curNet.getKey() in self.telemetryWindows:
                                telemetryWindow = self.telemetryWindows[curNet.getKey()]
                                telemetryWindow.updateNetworkData(curNet)            

                            # 3 scenarios: 
                            # 20 MHz, 1 channel
                            # 40 MHz, 2nd channel above/below or non-contiguous for 5 GHz
                            # 80/160 MHz, Specified differently.  It's allocated as a contiguous block
                            if curNet.channel < 15:
                                # 2.4 GHz
                                for i in range(0, 15):
                                    graphPoint = False
                                    
                                    if (curNet.bandwidth == 20):
                                        if i >= (curNet.channel - 1) and i <=(curNet.channel +1):
                                            graphPoint = True
                                    elif (curNet.bandwidth== 40):
                                        if curNet.secondaryChannelLocation == 'above':
                                            if i >= (curNet.channel - 1) and i <=(curNet.channel +5):
                                                graphPoint = True
                                        else:
                                            if i >= (curNet.channel - 5) and i <=(curNet.channel +1):
                                                graphPoint = True
                                    elif (curNet.bandwidth == 80):
                                            if i >= (curNet.channel - 1) and i <=(curNet.channel +15):
                                                graphPoint = True
                                    elif (curNet.bandwidth == 160):
                                            if i >= (curNet.channel - 1) and i <=(curNet.channel +29):
                                                graphPoint = True
                                            
                                    if graphPoint:
                                        if curNet.signal >= -100:
                                            curSeries.replace(i, i, curNet.signal)
                                        else:
                                            curSeries.replace(i, i, -100)
                                    else:
                                        curSeries.replace(i, i, -100)
                            else:
                                # 5 GHz
                                for i in range(33, 171):
                                    graphPoint = False
                                    
                                    if (curNet.bandwidth == 20):
                                        if i >= (curNet.channel - 1) and i <=(curNet.channel +1):
                                            graphPoint = True
                                    elif (curNet.bandwidth== 40):
                                        if curNet.secondaryChannelLocation == 'above':
                                            if i >= (curNet.channel - 1) and i <=(curNet.channel +5):
                                                graphPoint = True
                                        else:
                                            if i >= (curNet.channel - 5) and i <=(curNet.channel +1):
                                                graphPoint = True
                                    elif (curNet.bandwidth == 80):
                                            if i >= (curNet.channel - 1) and i <=(curNet.channel +15):
                                                graphPoint = True
                                    elif (curNet.bandwidth == 160):
                                            if i >= (curNet.channel - 1) and i <=(curNet.channel +29):
                                                graphPoint = True
                                            
                                    if graphPoint:
                                        if curNet.signal >= -100:
                                            curSeries.replace(i-33, i, curNet.signal)
                                        else:
                                            curSeries.replace(i-33, i, -100)
                                    else:
                                        curSeries.replace(i-33, i, -100)
                                        
                            break;
                    
        # self.networkTable.insertRow(rowPosition)
        
        for curKey in wirelessNetworks.keys():
            # Don't add duplicate
            if (wirelessNetworks[curKey].foundInList):
                continue
                
            nextColor = colors[self.nextColor]
            self.nextColor += 1
            
            if (self.nextColor >= len(colors)):
                self.nextColor = 0
                
            newSeries = QLineSeries()
            pen = QPen(nextColor)
            pen.setWidth(2)
            newSeries.setPen(pen)
            
            curNet = wirelessNetworks[curKey]
            # 3 scenarios: 
            # 20 MHz, 1 channel
            # 40 MHz, 2nd channel above/below or non-contiguous for 5 GHz
            # 80/160 MHz, Specified differently.  It's allocated as a contiguous block
            if curNet.channel < 15:
                # 2.4 GHz
                for i in range(0, 15):
                    # 2.4 GHz channels overlap by 2 in each direction
                    graphPoint = False
                    
                    if (curNet.bandwidth == 20):
                        if i >= (curNet.channel - 1) and i <=(curNet.channel +1):
                            graphPoint = True
                    elif (curNet.bandwidth== 40):
                        if curNet.secondaryChannelLocation == 'above':
                            if i >= (curNet.channel - 1) and i <=(curNet.channel +5):
                                graphPoint = True
                        else:
                            if i >= (curNet.channel - 5) and i <=(curNet.channel +1):
                                graphPoint = True
                    elif (curNet.bandwidth == 80):
                            if i >= (curNet.channel - 1) and i <=(curNet.channel +15):
                                graphPoint = True
                    elif (curNet.bandwidth == 160):
                            if i >= (curNet.channel - 1) and i <=(curNet.channel +29):
                                graphPoint = True
                            
                    if graphPoint:
                        if curNet.signal >= -100:
                            newSeries.append( i, curNet.signal)
                        else:
                            newSeries.append(i, -100)
                    else:
                            newSeries.append(i, -100)
                        
                newSeries.setName(curNet.getKey())
                
                self.chart24.addSeries(newSeries)
                newSeries.attachAxis(self.chart24.axisX())
                newSeries.attachAxis(self.chart24.axisY())
            else:
                # 5 GHz
                for i in range(33, 171):
                    graphPoint = False
                    
                    if (curNet.bandwidth == 20):
                        if i >= (curNet.channel - 1) and i <=(curNet.channel +1):
                            graphPoint = True
                    elif (curNet.bandwidth== 40):
                        if curNet.secondaryChannelLocation == 'above':
                            if i >= (curNet.channel - 1) and i <=(curNet.channel +5):
                                graphPoint = True
                        else:
                            if i >= (curNet.channel - 5) and i <=(curNet.channel +1):
                                graphPoint = True
                    elif (curNet.bandwidth == 80):
                            if i >= (curNet.channel - 1) and i <=(curNet.channel +15):
                                graphPoint = True
                    elif (curNet.bandwidth == 160):
                            if i >= (curNet.channel - 1) and i <=(curNet.channel +29):
                                graphPoint = True
                            
                    if graphPoint:
                        if curNet.signal >= -100:
                            newSeries.append( i, curNet.signal)
                        else:
                            newSeries.append(i, -100)
                    else:
                            newSeries.append(i, -100)
                        
                newSeries.setName(curNet.getKey())
                
                self.chart5.addSeries(newSeries)
                newSeries.attachAxis(self.chart5.axisX())
                newSeries.attachAxis(self.chart5.axisY())
                
            # Do the table second so we can attach the series to it.
            rowPosition = self.networkTable.rowCount()
            rowPosition -= 1
            addedFirstRow = False
            if rowPosition < 0:
                addedFirstRow = True
                rowPosition = 0
                
            self.networkTable.insertRow(rowPosition)
            
            if (addedFirstRow):
                self.networkTable.setRowCount(1)

            self.networkTable.setItem(rowPosition, 0, QTableWidgetItem(wirelessNetworks[curKey].macAddr))
            tmpssid = wirelessNetworks[curKey].ssid
            if (len(tmpssid) == 0):
                tmpssid = '<Unknown>'
            newSSID = QTableWidgetItem(tmpssid)
            ssidBrush = QBrush(nextColor)
            newSSID.setForeground(ssidBrush)
            # You can bind more than one data.  See this: 
            # https://stackoverflow.com/questions/2579579/qt-how-to-associate-data-with-qtablewidgetitem
            newSSID.setData(Qt.UserRole, newSeries)
            newSSID.setData(Qt.UserRole+1, wirelessNetworks[curKey])
            newSSID.setData(Qt.UserRole+2, None)
            
            self.networkTable.setItem(rowPosition, 1, newSSID)
            self.networkTable.setItem(rowPosition, 2, QTableWidgetItem(wirelessNetworks[curKey].security))
            self.networkTable.setItem(rowPosition, 3, QTableWidgetItem(wirelessNetworks[curKey].privacy))
            self.networkTable.setItem(rowPosition, 4, IntTableWidgetItem(str(wirelessNetworks[curKey].getChannelString())))
            self.networkTable.setItem(rowPosition, 5, IntTableWidgetItem(str(wirelessNetworks[curKey].frequency)))
            self.networkTable.setItem(rowPosition, 6,  IntTableWidgetItem(str(wirelessNetworks[curKey].signal)))
            self.networkTable.setItem(rowPosition, 7, IntTableWidgetItem(str(wirelessNetworks[curKey].bandwidth)))
            self.networkTable.setItem(rowPosition, 8, DateTableWidgetItem(wirelessNetworks[curKey].lastSeen.strftime("%m/%d/%Y %H:%M:%S")))
            self.networkTable.setItem(rowPosition, 9, DateTableWidgetItem(wirelessNetworks[curKey].firstSeen.strftime("%m/%d/%Y %H:%M:%S")))
            if wirelessNetworks[curKey].gps.isValid:
                self.networkTable.setItem(rowPosition, 10, QTableWidgetItem('Yes'))
            else:
                self.networkTable.setItem(rowPosition, 10, QTableWidgetItem('No'))

        # Clean up any empty rows because of the way QTableWidget is handling row inserts
        numRows = self.networkTable.rowCount()

        # Last rounds of checks and cleanups
        
        # Check for dangling QTableWidget rows and if we've checked the timeoutcheckbox, remove items.
        if numRows > 0:
            # Handle if timeout checkbox is checked
            maxTime = datetime.datetime.now() - datetime.timedelta(minutes=3)

            rowPosition = numRows - 1  #  convert count to index
            # range goes to last 
            for i in range(rowPosition, -1, -1):
                try:
                    curData = self.networkTable.item(i, 1).data(Qt.UserRole+1)
                    
                    # Age out
                    if self.cbAgeOut.isChecked():
                        if curData.lastSeen < maxTime:
                            curSeries = self.networkTable.item(i, 1).data(Qt.UserRole)
                            if curData.channel < 20:
                                self.chart24.removeSeries(curSeries)
                            else:
                                self.chart5.removeSeries(curSeries)
                                
                            self.networkTable.removeRow(i)
                        
                except:
                    curData = None
                    self.networkTable.removeRow(i)

        # See if we have any telemetry windows that are no longer in the network table and not visible
        numRows = self.networkTable.rowCount()
        
        if (numRows > 0) and (len(self.telemetryWindows.keys()) > 0):
            # Build key list just once to cut down # of loops
            netKeyList = []
            for i in range(0, numRows):
                curNet = self.networkTable.item(i, 1).data(Qt.UserRole+1)
                netKeyList.append(curNet.getKey())
                
            try:
                # If the length of this dictionary changes it may throw an exception.
                # We'll just pick it up next pass.  This is low-priority cleanup
                
                for curKey in self.telemetryWindows.keys():
                    # For each telemetry window we have stored,
                    # If it's no longer in the network table and it's not visible
                    # (Meaning the window was closed but we still have an active Window object)
                    # Let's inform the window to close and remove it from the list
                    if curKey not in netKeyList:
                        if not self.telemetryWindows[curKey].isVisible():
                            self.telemetryWindows[curKey].close()
                            del self.telemetryWindows[curKey]
            except:
                pass
        # Last formatting tweaks on network table
        self.networkTable.resizeColumnsToContents()
        self.networkTable.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        
    def onInterface(self):
        pass
            
    def onClearData(self):
        self.networkTable.setRowCount(0)
        self.chart24.removeAllSeries()
        self.chart5.removeAllSeries()
        
        
    def openFileDialog(self):    
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        fileName, _ = QFileDialog.getOpenFileName(self,"QFileDialog.getOpenFileName()", "","CSV Files (*.csv);;All Files (*)", options=options)
        if fileName:
            return fileName
        else:
            return None
 
    def saveFileDialog(self):    
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        fileName, _ = QFileDialog.getSaveFileName(self,"QFileDialog.getSaveFileName()","","CSV Files (*.csv);;All Files (*)", options=options)
        if fileName:
            return fileName
        else:
            return None

    def importData(self):
        fileName = self.openFileDialog()

        if not fileName:
            return
            
        wirelessNetworks = {}
        
        with open(fileName, 'r') as f:
            reader = csv.reader(f)
            raw_list = list(reader)
            
            # remove blank lines
            while [] in raw_list:
                raw_list.remove([])
                
            if len(raw_list) > 1:
                # Check header row looks okay
                if raw_list[0][0] != 'macAddr' or (len(raw_list[0]) < 21):
                    QMessageBox.question(self, 'Error',"File format doesn't look like an exported scan.", QMessageBox.Ok)
                    return
                        
                # Ignore header row
                for i in range (1, len(raw_list)):
                    if (len(raw_list[i]) >= 21):
                        newNet = WirelessNetwork()
                        newNet.macAddr=raw_list[i][0]
                        newNet.ssid = raw_list[i][1]
                        newNet.security = raw_list[i][2]
                        newNet.privacy = raw_list[i][3]
                        
                        # Channel could be primary+secondary
                        channelstr = raw_list[i][4]
                        
                        if '+' in channelstr:
                            newNet.channel = int(channelstr.split('+')[0])
                            newNet.secondaryChannel = int(channelstr.split('+')[1])
                            
                            if newNet.secondaryChannel > newNet.channel:
                                newNet.secondaryChannelLocation = 'above'
                            else:
                                newNet.secondaryChannelLocation = 'below'
                        else:
                            newNet.channel = int(raw_list[i][4])
                            newNet.secondaryChannel = 0
                            newNet.secondaryChannelLocation = 'none'
                        
                        newNet.frequency = int(raw_list[i][5])
                        newNet.signal = int(raw_list[i][6])
                        newNet.strongestsignal = int(raw_list[i][7])
                        newNet.bandwidth = int(raw_list[i][8])
                        newNet.lastSeen = parser.parse(raw_list[i][9])
                        newNet.firstSeen = parser.parse(raw_list[i][10])
                        newNet.gps.isValid = stringtobool(raw_list[i][11])
                        newNet.gps.latitude = float(raw_list[i][12])
                        newNet.gps.longitude = float(raw_list[i][13])
                        newNet.gps.altitude = float(raw_list[i][14])
                        newNet.gps.speed = float(raw_list[i][15])
                        newNet.strongestgps.isValid = stringtobool(raw_list[i][16])
                        newNet.strongestgps.latitude = float(raw_list[i][17])
                        newNet.strongestgps.longitude = float(raw_list[i][18])
                        newNet.strongestgps.altitude = float(raw_list[i][19])
                        newNet.strongestgps.speed = float(raw_list[i][20])
                        
                        wirelessNetworks[newNet.getKey()] = newNet
                    
        if len(wirelessNetworks) > 0:
            self.onClearData()
            self.populateTable(wirelessNetworks)

    def exportData(self):
        fileName = self.saveFileDialog()

        if not fileName:
            return
            
        try:
            outputFile = open(fileName, 'w')
        except:
            QMessageBox.question(self, 'Error',"Unable to write to " + fileName, QMessageBox.Ok)
            return
            
        outputFile.write('macAddr,SSID,Security,Privacy,Channel,Frequency,Signal Strength,Strongest Signal Strength, Bandwidth,Last Seen,First Seen,GPS Valid,Latitude,Longitude,Altitude,Speed,Strongest GPS Valid,Strongest Latitude,Strongest Longitude,Strongest Altitude,Strongest Speed\n')

        numItems = self.networkTable.rowCount()
        
        if numItems == 0:
            outputFile.close()
            return
           
        for i in range(0, numItems):
            curData = self.networkTable.item(i, 1).data(Qt.UserRole+1)

            outputFile.write(self.networkTable.item(i, 0).text() + ',' + self.networkTable.item(i, 1).text() + ',' + self.networkTable.item(i, 2).text() + ',' + self.networkTable.item(i, 3).text())
            outputFile.write(',' + self.networkTable.item(i, 4).text()+ ',' + self.networkTable.item(i, 5).text()+ ',' + self.networkTable.item(i, 6).text()+ ',' + str(curData.strongestsignal) + ',' + self.networkTable.item(i, 7).text() + ',' +
                                    curData.lastSeen.strftime("%m/%d/%Y %H:%M:%S") + ',' + curData.firstSeen.strftime("%m/%d/%Y %H:%M:%S") + ',' + 
                                    str(curData.gps.isValid) + ',' + str(curData.gps.latitude) + ',' + str(curData.gps.longitude) + ',' + str(curData.gps.altitude) + ',' + str(curData.gps.speed) + ',' + 
                                    str(curData.strongestgps.isValid) + ',' + str(curData.strongestgps.latitude) + ',' + str(curData.strongestgps.longitude) + ',' + str(curData.strongestgps.altitude) + ',' + str(curData.strongestgps.speed) + '\n')
            
        outputFile.close()
        
    def center(self):
        # Get our geometry
        qr = self.frameGeometry()
        # Find the desktop center point
        cp = QDesktopWidget().availableGeometry().center()
        # Move our center point to the desktop center point
        qr.moveCenter(cp)
        # Move the top-left point of the application window to the top-left point of the qr rectangle, 
        # basically centering the window
        self.move(qr.topLeft())
        
    def requestRemoteInterfaces(self):
        url = "http://" + self.remoteAgentIP + ":" + str(self.remoteAgentPort) + "/wireless/interfaces"
        statusCode, responsestr = makeGetRequest(url)
        
        if statusCode == 200:
            try:
                interfaces = json.loads(responsestr)
                
                retList = interfaces['interfaces']
                return statusCode, retList
            except:
                return statusCode, None
        else:
            return statusCode, None

    def onRemoteAgent(self):
        if (self.menuRemoteAgent.isChecked() == self.lastRemoteState):
            # There's an extra bounce in this for some reason.
            return
            
        if self.menuRemoteAgent.isChecked():
            # We're transitioning to a remote agent
            text, okPressed = QInputDialog.getText(self, "Remote Agent","Please provide IP:port:", QLineEdit.Normal, "127.0.0.1:8020")
            if okPressed and text != '':
                # Validate the input
                p = re.compile('^([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}:[0-9]{1,5})')
                specIsGood = True
                try:
                    agentSpec = p.search(text).group(1)
                    self.remoteAgentIP = agentSpec.split(':')[0]
                    self.remoteAgentPort = int(agentSpec.split(':')[1])
                    
                    if self.remoteAgentPort < 1 or self.remoteAgentPort > 65535:
                        QMessageBox.question(self, 'Error',"Port must be in an acceptable IP range (1-65535)", QMessageBox.Ok)
                        self.menuRemoteAgent.setChecked(False)
                        specIsGood = False
                except:
                    QMessageBox.question(self, 'Error',"Please enter it in the format <IP>:<port>", QMessageBox.Ok)
                    self.menuRemoteAgent.setChecked(False)
                    specIsGood = False
                    
                if not specIsGood:
                    return
                    
                # If we're here we're good.
                reply = QMessageBox.question(self, 'Question',"Would you like updates to happen automatically?", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)

                if reply == QMessageBox.Yes:
                    self.remoteAutoUpdates = True
                else:
                    self.remoteAutoUpdates = False

                # Configure the GUI.
                self.lblInterface.setText("Remote Interface")
                statusCode, interfaces = self.requestRemoteInterfaces()
                
                if statusCode != 200:
                    QMessageBox.question(self, 'Error',"An error occurred getting the remote interfaces.  Please check that the agent is running.", QMessageBox.Ok)
                    self.menuRemoteAgent.setChecked(False)
                    self.lblInterface.setText("Local Interface")
                    return
                    
                # Okay, we have interfaces.  Let's load them
                self.combo.clear()
                if (len(interfaces) > 0):
                    for curInterface in interfaces:
                        self.combo.addItem(curInterface)
                else:
                    self.statusBar().showMessage('No wireless interfaces found.')
                    
                self.lastRemoteState = self.menuRemoteAgent.isChecked() 
                
                self.onGPSStatus()
            else:
                # Stay local.
                self.menuRemoteAgent.setChecked(False)
        else:
            # We're transitioning local
            self.lblInterface.setText("Local Interface")
            self.combo.clear()
            interfaces=WirelessEngine.getInterfaces()
            
            if (len(interfaces) > 0):
                for curInterface in interfaces:
                    self.combo.addItem(curInterface)
            else:
                self.statusBar().showMessage('No wireless interfaces found.')

            self.lastRemoteState = self.menuRemoteAgent.isChecked() 
            self.onGPSStatus()

    def onAbout(self):
        aboutMsg = "Sparrow-wifi 802.11 WiFi Graphic Analyzer\n"
        aboutMsg += "Written by ghostop14\n"
        aboutMsg += "https://github.com/ghostop14\n\n"
        aboutMsg += "This application is open source and licensed\n"
        aboutMsg += "under the terms fo the GPL version 3\n"
        
        QMessageBox.question(self, 'Message',aboutMsg, QMessageBox.Ok)
        
    def closeEvent(self, event):
        # reply = QMessageBox.question(self, 'Message',"Are you sure to quit?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        # if reply == QMessageBox.Yes:
            # event.accept()
        #else:
            # event.ignore()       
        if self.scanRunning:
            QMessageBox.question(self, 'Error',"Please stop the running scan first.", QMessageBox.Ok)
            event.ignore()
        else:
            event.accept()


# -------  Main Routine -------------------------

if __name__ == '__main__':
    
    app = QApplication(sys.argv)
    mainWin = mainWindow()
    sys.exit(app.exec_())
    
