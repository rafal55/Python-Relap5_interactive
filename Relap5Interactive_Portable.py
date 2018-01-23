#C:\Python27\python
# Author: Rafal Baranowski, NCBJ


#Two major features of Relap5Interactive.py allow you to:
#	+ Plot data from the rstplt file on fly while running Relap simulation,
#	+ Modify the Relap input file on fly without caring about the restart file and steps needed for it.
#In particular, Relap5Interactive.py gives you an ability to:
#	+ Modify created plots by deleting, adding or changing their number or number of variables drawn on them,
#	+ Save created plots in form of a multipage pdf file or other formats like: png, ps and svg,
#	+ Use the original input file on fly for introducing changes to the model,
#	  this however, does not include addition or deletion of existing cards, it is not supported. 
#	+ Apply changes any number of times

#Comments:
#Any change made to the parameters on the simulation cards in the input file triggers Relap to restart. 
#It should be known that for the purpose of the restart Relap uses the rstplt file
#where simulation data and restart data are saved with a defined frequency.
#Thus, it can happen that plotted data will appear with a step back resulting from the low frequency
#of restart data writing. One of the solutions to avoid this is to increase the frequency 
#of the restart data writing, this however, leads to quickly increasing size of the rstplt file
#and is not practical for long run simulations. The advice is to use a high frequency for time intervals
#when changes in the input file are foreseen and a low frequency elsewhere. Since, any changes to the input file
#can be made on fly the frequency can be very conveniently  adjusted at any time of the simulation. 

#An example of figures specification:
#Caption1,    Power [W],                     rktpow 0,          Reactor Power
#Caption2,    Temperature [K],               httemp 340000917,  Cladding core center
#Caption3,    Downcomer Water level [m],     cntrlvar 172,      SG at the intact loop,      cntrlvar 272,  SG at the broken loop

import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import warnings
import subprocess
import shutil
import time
import sys
import re
import os

mpl.rcParams['axes.color_cycle'] = 'k, r, b, g, c, m, y'

class StrippedInput(object):
	"""Class for striping Relap5 input file"""

	def __init__(self, inpfile):
		"""Instantiation purifies input file and returns it as a dictionary of cards
		and a list of figures to be plotted"""
		
		self.file = open(inpfile, "r")
		self.Cards = {}
		self.CardPrm = []
		for line in self.file:
			card = re.match('\d.*', line)
			if card:
				card=card.group().strip()
				card=re.split('\r',card)
				card=re.split('[*\s]+[*]|[*]',card[0])
				card=re.split('[*\s]+[$]|[*]',card[0])
				card=re.split('\s+|[,]\s*',card[0])
				self.CardParm=card[1:]
				self.Cards.update({card[0]:self.CardParm})
		self.file.close()

		self.file = open(inpfile, "r")
		self.Figures = []
		for line in self.file:
				end_card = re.match('[.]', line)
				if end_card:
					for line in self.file:
						fig_card = re.match('\w.*', line)
						if fig_card:
							fig_card=fig_card.group().strip()
							fig_card=re.split('\r',fig_card)
							fig_card=re.split('[*\s]+[*]|[*]',fig_card[0])
							fig_card=re.split('[*\s]+[$]|[*]',fig_card[0])
							fig_card=re.split(',\s+',fig_card[0])
							self.Figures.append(fig_card)
		self.file.close()

def check_input_cards(Relap,input1, input2):
	"""Method compares two inputs and returns cards that have been changed"""
	global CARDS
	cards = {}

	if len(input2.Cards.keys()) > len(input1.Cards.keys()):
		CARDS = 1
		print("\n\nSome cards were added. Option not supported !!!\n\n")
		_exit(Relap) 

	if len(input2.Cards.keys()) < len(input1.Cards.keys()):
		CARDS = -1
		print("\n\nSome cards were deleted. Option not supported !!!\n\n")
		_exit(Relap) 

	if len(input2.Cards.keys()) == len(input1.Cards.keys()):
		CARDS = 0
		for card in input1.Cards.keys():
			if input1.Cards.get(card) != input2.Cards.get(card):
				cards.update({card:input2.Cards.get(card)})
				CARDS = 1
	
	if CARDS == 1: 
		print("\n\nChanges have been introduced on the following cards:")
		for k, v in sorted(cards.items()):
			print ("\n%s=%s" % (k, v))
		print ("\n\n")
	return cards

def check_input_figs(input1, input2):
	"""Method compares two inputs and returns cards that are defferent in a form of a dictionary"""
	global FIGS
	
	if len(input1.Figures) == 0:
		txt = plt.text(0.5, 0.5,'No plots have been specified', ha='center', va='center', fontsize=20)	

	if len(input2.Figures) > len(input1.Figures):
		FIGS = 1

	if len(input2.Figures) < len(input1.Figures):
		FIGS = -1	

	if len(input2.Figures) == len(input1.Figures):
		FIGS = 0
		for fig in range(len(input2.Figures)):
			if input2.Figures[fig] != input1.Figures[fig]:
				FIGS = 1
				
def create_strip_file(figures):
	"""Method constructs the strip file"""
	with open("strip.i","w+") as f:
		f.write('= stripping file\n100 strip\n103 0\n')
		count=0
		for fig in range(len(figures)):
			for plt in range(2,len(figures[fig]),2):
				f.write(('%d ' + str(figures[fig][plt])+'\n') % (1000+count+1))
				count+=1
		f.write('.')

def rest_time_cards(New_Input):
	"""Method constructs time cards for the restart file"""
	time_cards = {}
	for card in range(len(New_Input.Cards.keys())):
			tcard = re.match('2\d{2}(?!\d)', New_Input.Cards.keys()[card])
			if tcard:
				tcard=tcard.group()
				time_cards.update({tcard:New_Input.Cards.get(tcard)})
	return time_cards

def cnv_card_type(New_Input):
	"""Method checks control variables format"""
	cnv_type = 'short'
	for card in New_Input.Cards.keys():
		cnv_card = re.match('20500000', card)
		if cnv_card:
			cnv_card = cnv_card.group()
			cnv_type =  New_Input.Cards.get(cnv_card)
	if cnv_type == ['9999'] or cnv_type == ['4095']:
		cnv_type = 'long'
	
	return cnv_type

def cards_interpreter(New_Input, cards):
	"""Method constructs components cards for the restart file"""
	components = {}
	hyd_cards = []
	comp_cards = []

	cnv_type = cnv_card_type(New_Input)

	for card in cards.keys():
		if len(card) == 7: 
			hyd = re.match('\A\d{3}', card)
			if hyd:
				hyd = hyd.group()
				hyd_cards.append(hyd)
		if len(card) == 8: 
			rk = re.match('\A[3]\d{3}', card)
			if rk:
				rk = rk.group()
				comp_cards.append(rk)	
			if cnv_type == 'short':
				cnv = re.match('\A[2][0][5]\d{3}', card)
				if cnv:
					cnv = cnv.group()
					comp_cards.append(cnv)
			if cnv_type == 'long':
				cnv = re.match('\A[2][0][5]\d{4}', card)
				if cnv:
					cnv = cnv.group()
					comp_cards.append(cnv)
			tbl = re.match('\A[2][0][2]\d{3}', card)
			if tbl:
				tbl = tbl.group()
				comp_cards.append(tbl)
			htst = re.match('\A[1]\d{3}', card)
			if htst:
				htst = htst.group()
				comp_cards.append(htst)
			http = re.match('\A[2][0][1]\d{3}', card)
			if http:
				http = http.group()
				comp_cards.append(http)

	comp_cards = list(set(comp_cards))

	components.update(cards)
	components.update(hyddyn_comps(New_Input, hyd_cards))
	components.update(other_comps(New_Input, comp_cards))

	return components

def hyddyn_comps(New_Input, hyd_cards):
	"""Method constructs hydrodynamic comp. from the given cards"""
	hyd_comps = {}
	
	for hyd in hyd_cards:
		for card in New_Input.Cards.keys():
			if len(card) == 7:
				hydd = re.match('\A'+hyd+'\d+', card)
				if hydd:
					hydd = hydd.group()
					hyd_comps.update({hydd : New_Input.Cards.get(hydd)})

	return hyd_comps

def other_comps(New_Input, cards):
	"""Method constructs components from the given cards"""
	comps = {}

	for car in cards:
		for card in New_Input.Cards.keys():
			if len(card) == 8:
				carr = re.match('\A'+car+'\d+', card)
				if carr:
					carr = carr.group()
					comps.update({carr : New_Input.Cards.get(carr)})
	
	return comps

def rest_file(cards, New_Input):
	"""Method constructs the restart file"""
	rest_rq_cards={'100':['restart','transnt'],'103':['-1','rstplt']}
	
	cards.update(rest_rq_cards)
	cards.update(rest_time_cards(New_Input))
	cards.update(cards_interpreter(New_Input, cards))

	with open('transnt.i','w') as transf:
		for k, v in sorted(cards.items()):
			transf.write(k+'  '+'  '.join(map(str, v))+'\n')
		transf.write('.')
	
def prepare_data():
	"""Method prepares the stripf file for data plotting"""
	with warnings.catch_warnings():
		warnings.simplefilter("ignore")

		f = open('stripf','r')
		temp = f.read()
		temp = temp.split("plotrec")
		temp = [line.replace('\n', ' ') for line in temp[1:] ]
		temp = '\n'.join(temp)
		f = open('stripf','w')
		f.write(str(temp))
		f = open('stripf','r')
	
		return np.genfromtxt(f, unpack=True)

def run_strip(Figures):
	"""Method executes the Relap5's strip mode"""
	for f in ['stripf','outdtaStrip','rstpltStrip','logStrip']:
		if os.path.isfile(f): os.remove(f)
	shutil.copy('rstplt', 'rstpltStrip')

	create_strip_file(Figures)
	RelapStrip = subprocess.Popen(Relap_exe.get()+' -i strip.i -o outdtaStrip -r rstpltStrip > logStrip', shell=True)
	RelapStrip.wait()
	Data = prepare_data()

	return Data

	
def plot_data(Figures,Data,fr):
	"""Method plots data using the matplotlib library """
	txt=[]

	if FIGS == -1:
		plt.close("all")
		fr = True

	datacount=1 
	for fig in range(1,len(Figures)+1):
		plt.figure(fig)


		for plot in range(2,len(Figures[fig-1]),2):
			if plot + 1 < len(Figures[fig-1]):
				plt.plot(Data[0], Data[datacount], label=Figures[fig-1][plot+1])
				plt.legend(fancybox=True,fontsize=11).draggable()
			else: 
				plt.plot(Data[0], Data[datacount])
			datacount+=1
			plt.hold(True)	
		plt.hold(False)
		plt.grid()
		plt.xlabel('Time [s]')
		plt.ylabel(Figures[fig-1][1])
		plt.ticklabel_format(style='sci', axis='y', scilimits=(-4,4))
		plt.autoscale(tight=False)
		plt.tight_layout()
		plt.margins(0.001, 0.1)
		place_fig_win(fig, fr)

		try:
			txt.append(plt.figtext(0.3, 0.96, 'Latest value: ' + str(Data[datacount-1][-1])))
		except:
			txt.append(plt.figtext(0.3, 0.96, 'Latest value: ' + str(Data[datacount-1])))

	plt.pause(3-len(Figures)/30)
	for tx in txt: tx.remove()

def place_fig_win(fig, fr):
	
	mngr = plt.get_current_fig_manager()
	if fr or FIGS != 0:
		if fig <=3:
			geo = "%dx%d%+d%+d" % (556, 454, (fig-1)*556, 0)
			mngr.window.geometry(geo)
		else:
			geo = "%dx%d%+d%+d" % (556, 454, (fig-4)*20, 494)
			mngr.window.geometry(geo)

def save_plots(Figures,figformat):
	
	if figformat == 'png' or figformat == 'ps' or figformat == 'svg':
		write_plots_to_folder(Figures, figformat)
	else:
		write_plots_to_PDF(Figures)  		

def write_plots_to_PDF(Figures):

	mpl.rcParams['savefig.format'] = 'pdf'
	pp = PdfPages(os.getcwd()+'/Plots.pdf')
		
	for fig in range(1,len(Figures)+1):
		plt.figure(fig)
		plt.gca().set_position((.15, .16, .82, .80)) # to make a bit of room for extra text
		plt.figtext(0.03, 0.03,"Figure "+str(fig)+". "+ Figures[fig-1][0], fontsize=11)
		pp.savefig(fig)
	
	raw_input('\n\tPlots have been written to pdf file. Press enter.')
	pp.close()

def write_plots_to_folder(Figures, figformat):

	mpl.rcParams['savefig.format'] = figformat
		
	if not os.path.exists(os.getcwd()+'/Plots'):
		os.makedirs(os.getcwd()+'/Plots')
	
	for fig in range(1,len(Figures)+1):
		plt.figure(fig)
		plt.savefig(os.getcwd()+'/Plots/'+Figures[fig-1][0])
		
	raw_input('\n\tPlots have been saved to "Plots" folder. Press enter.')


def clean():

	for f in ['stripf','strip.i','outdtaStrip','rstpltStrip','logStrip','rstpltStrip',
			'screen','fort.9','fort.12','StripOnFly', 'relap_inp.i', 'transnt.i', 'read_steam_comment.o']:
		if os.path.isfile(f): os.remove(f)

def all_clean():

	clean()
	for f in ['rstplt', 'outdta']:
		if os.path.isfile(f): os.remove(f)
	shutil.rmtree('/Plots', ignore_errors=True)

def _exit(Relap):

	Relap.kill()
	Relap.wait()
	clean()
	sys.exit() 


def main(Relap_exe, input_dir, input_name, figform):
	

	root.destroy()
	try:
		os.chdir(input_dir.get())
	except:
		raw_input("\nCannot find input file directory. Press enter and try again.\n")
		sys.exit()

	all_clean()
	inputFile = input_name.get()
	figformat = figform.get()

	shutil.copy(inputFile, 'relap_inp.i')
	New_Input = Prev_Input = StrippedInput(inputFile)

	Relap = subprocess.Popen(Relap_exe.get()+' -i '+'relap_inp.i', shell = False)
	time.sleep(1)
	if Relap.poll() != None:	
		clean()
		sys.exit() 
	while os.path.isfile('rstplt') == False: time.sleep(1)

 	try:
 		fr = True
 		while Relap.poll() == None:
	
			New_Input = StrippedInput(inputFile)	
			cards = check_input_cards(Relap, Prev_Input, New_Input)
	
			if CARDS != 0:
				Relap.kill()
				Relap.wait()		
				os.remove('outdta')

				rest_file(cards, New_Input)
	
				Relap = subprocess.Popen(Relap_exe.get()+' -i '+'transnt.i', shell = False)
				time.sleep(1)
	
			check_input_figs(Prev_Input, New_Input)	

			Data = run_strip(New_Input.Figures)
			with warnings.catch_warnings():
				warnings.simplefilter("ignore")
				plot_data(New_Input.Figures, Data,fr)
				fr = False
			Prev_Input = New_Input

	except KeyboardInterrupt:
		raw_input('\n\t'"Press enter to save plots and exit.")
		save_plots(New_Input.Figures, figformat)
		_exit(Relap)

	raw_input('\n\t'"Press enter to save plots and exit.")
	save_plots(New_Input.Figures,figformat)
	clean()
	sys.exit()


##########################  GUI  ########################################
from Tkinter import *
import tkFileDialog
import FileDialog

def Relap():

	directory = tkFileDialog.askopenfilename()
	Relap_exe.set(directory)

def input_directory():

	directory = tkFileDialog.askopenfilename()
	dirr = os.path.split(directory)[0]
	name = os.path.split(directory)[1]
	input_dir.set(dirr)
	input_name.set(name)


root = Tk()
root.wm_title("Relap5Interactive")
logo = PhotoImage(file="R_logo.gif")

l1 = Label(root, text="Select RELAP5 executable file:", font= 8, height= 1)
l1.grid(column=0,row=0,sticky='W')

Relap_exe = StringVar()

entry = Entry(root, bd =5, width=40, font= 10, textvariable= Relap_exe)
entry.grid(column=0,row=1, sticky='EW')
entry.bind()

button = Button(root, text= 'Select', command=Relap)
button.grid(column=1,row=1)


l2 = Label(root, text="Select input file:", font= 8, height= 1)
l2.grid(column=0,row=2,sticky='W')

input_dir = StringVar()
input_name = StringVar()

entry2 = Entry(root, bd =5, width=40,  font= 10, textvariable= input_dir)
entry2.grid(column=0,row=3,sticky='EW')
entry2.bind()

button2 = Button(root, text= 'Select', command=input_directory)
button2.grid(column=1,row=3)


l4 = Label(root, text="Plot saving format:", font= 6, height= 1)
l4.grid(column=0,row=4,sticky='E')

figform = StringVar(root)
figform.set("pdf") # default value

w = OptionMenu(root, figform, "pdf", "png", "ps", "svg")
w.grid(column=1,row=4,sticky='E')


button3 = Button(root, bd =5, text= 'Run RELAP5', image=logo, compound="center", font = "Helvetica 16 bold italic", command=lambda: main(Relap_exe, input_dir, input_name, figform))
button3.grid(column=0,row=5)

root.grid_columnconfigure(0,weight=1)
root.resizable(False,False)

root.mainloop()
