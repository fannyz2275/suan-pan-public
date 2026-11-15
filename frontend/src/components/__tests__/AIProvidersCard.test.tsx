import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import api from '@/lib/api'
import AIProvidersCard from '../AIProvidersCard'
vi.mock('@/lib/api',()=>({default:{get:vi.fn(),put:vi.fn(),post:vi.fn(),delete:vi.fn()}}))
beforeEach(()=>{vi.clearAllMocks(); vi.mocked(api.get).mockResolvedValue({data:{available:true,providers:[{provider:'gemini',configured:false,enabled:true},{provider:'openrouter',configured:false,enabled:false}]}})})
it('writes key once and clears the input; never receives a key back',async()=>{
 render(<AIProvidersCard />)
 const input=await screen.findByLabelText('Gemini API key')
 expect(input).toHaveAttribute('type','password')
 await userEvent.type(input,'synthetic-secret-1234')
 vi.mocked(api.put).mockResolvedValue({data:{saved:true}})
 await userEvent.click(screen.getByRole('button',{name:'Save Gemini key'}))
 await waitFor(()=>expect(api.put).toHaveBeenCalledWith('/profile/ai-providers/gemini',{api_key:'synthetic-secret-1234'}))
 await waitFor(()=>expect(input).toHaveValue(''))
 expect(screen.getByText(/Advisor chat can still use this key/)).toBeInTheDocument()
})
it('does not show an upstream error body containing a secret',async()=>{
 render(<AIProvidersCard />)
 await userEvent.type(await screen.findByLabelText('Gemini API key'),'synthetic-secret-1234')
 vi.mocked(api.put).mockRejectedValue({response:{data:{detail:'synthetic-secret-1234'}}})
 await userEvent.click(screen.getByRole('button',{name:'Save Gemini key'}))
 expect(await screen.findByRole('alert')).not.toHaveTextContent('synthetic-secret-1234')
})
